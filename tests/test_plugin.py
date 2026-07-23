from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "team_scores_external",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def manifest():
    return json.loads((ROOT / "manifest.json").read_text())


def response(payload):
    result = Mock()
    result.json.return_value = payload
    result.raise_for_status.return_value = None
    return result


def test_manifest_and_plugin_id():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    assert plugin.plugin_id == "team_scores"
    assert manifest()["version"] == "1.4.0"
    assert manifest()["settings_schema"]["properties"]["trigger_on_started"]["default"] is True
    assert manifest()["settings_schema"]["properties"]["live_refresh_seconds"]["default"] == 30


def test_fiestaboard_loader_accepts_standalone_repo(tmp_path):
    from src.plugins.loader import PluginLoader

    (tmp_path / "team_scores").symlink_to(ROOT, target_is_directory=True)
    loader = PluginLoader(plugins_dir=tmp_path, external_dirs=[])
    plugin = loader.load_plugin("team_scores")
    assert plugin is not None, loader._load_errors.get("team_scores")


def test_filters_and_ranks_mlb_favorite_first():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {
        "leagues": ["MLB"],
        "mlb_teams": ["SEA"],
        "timezone": "UTC",
        "lookahead_days": 7,
        "final_max_age_hours": 48,
    }
    payload = {
        "dates": [{
            "games": [
                mlb_game(1, "SEA", "SF", "Live", "2026-07-13T20:00:00Z", 4, 2),
                mlb_game(2, "NYY", "BOS", "Final", "2026-07-13T18:00:00Z", 3, 1),
            ]
        }]
    }
    with patch.object(module.requests, "get", return_value=response(payload)) as request, patch.object(
        plugin, "_now", return_value=datetime(2026, 7, 13, 21, tzinfo=timezone.utc)
    ):
        result = plugin.fetch_data()

    assert result.available
    assert result.data["game_count"] == 1
    assert result.data["away_team"] == "SEA"
    assert result.data["state"] == "live"
    assert result.data["line1"] == "MLB"
    assert result.data["team_line"] == "{66}SEA 4 {64}SF 2"
    assert module._tile_count(result.data["team_line"]) <= 15
    assert len(result.data["line2"]) <= 15
    assert set(manifest()["variables"]["arrays"]["games"]["item_fields"]) <= set(
        result.data["games"][0]
    )
    assert request.call_args.kwargs["params"]["hydrate"] == (
        "team,linescore,probablePitcher,venue,broadcasts"
    )


def test_nfl_favorite_and_note_lines():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {
        "leagues": ["NFL"],
        "nfl_teams": ["SEA"],
        "timezone": "America/Los_Angeles",
        "lookahead_days": 7,
        "final_max_age_hours": 18,
    }
    payload = {"events": [nfl_game("SEA", "SF", "2026-07-14T20:00:00Z")]}
    with patch.object(module.requests, "get", return_value=response(payload)) as request, patch.object(
        plugin, "_now", return_value=datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    ):
        with plugin._bound_board(SimpleNamespace(device_type="note")):
            result = plugin.fetch_data()

    assert result.available
    assert result.data["league"] == "NFL"
    assert result.data["minutes_until_start"] == 1920
    assert result.data["line1"] == "NFL"
    assert result.data["line2"] == "SEA AT SF"
    assert result.data["team_line"] == "{66}SEA AT {63}SF"
    assert result.formatted_lines[1] == "{66}SEA AT {63}SF"
    assert result.data["away_record"] == "14-3"
    assert result.data["home_record"] == "12-5"
    assert result.data["broadcast"] == "NBC"
    assert result.data["venue"] == "Lumen Field"
    assert result.data["series_context"] == "Sunday Night Football"
    assert result.data["context_line"] == "NBC"
    assert all(module._tile_count(line) <= 15 for line in result.formatted_lines[:3])
    assert request.call_args.args[0] == module.ESPN_LEAGUES["NFL"]["url"]


def test_recent_final_ranks_ahead_of_upcoming_game():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {
        "leagues": ["MLB"],
        "mlb_teams": ["SEA"],
        "timezone": "UTC",
        "lookahead_days": 7,
        "final_max_age_hours": 18,
    }
    payload = {
        "dates": [{
            "games": [
                mlb_game(1, "SEA", "SF", "Final", "2026-07-13T18:00:00Z", 4, 2),
                mlb_game(2, "SEA", "LAD", "Preview", "2026-07-14T20:00:00Z", 0, 0),
            ]
        }]
    }
    with patch.object(module.requests, "get", return_value=response(payload)), patch.object(
        plugin, "_now", return_value=datetime(2026, 7, 13, 21, tzinfo=timezone.utc)
    ):
        result = plugin.fetch_data()

    assert result.data["event_id"] == "1"
    assert result.data["state"] == "final"
    assert result.data["header"] == "MLB SCORES"
    assert result.data["line1"] == "MLB"
    assert result.data["line3"] == "FINAL"


def test_mlb_warmup_remains_scheduled_until_play_begins():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    raw = mlb_game(1, "SEA", "SF", "Live", "2026-07-18T20:00:00Z", 0, 0)
    raw["status"]["detailedState"] = "Warmup"

    warmup = plugin._parse_mlb_game(raw, timezone.utc)
    raw["status"]["detailedState"] = "In Progress"
    active = plugin._parse_mlb_game(raw, timezone.utc)

    assert warmup["state"] == "scheduled"
    assert warmup["away_score"] == ""
    assert active["state"] == "live"


def test_postponed_game_uses_plain_league_header():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    raw = mlb_game(1, "SEA", "SF", "Preview", "2026-07-18T20:00:00Z", 0, 0)
    raw["status"]["detailedState"] = "Postponed"

    game = plugin._parse_mlb_game(raw, timezone.utc)
    display = plugin._display_fields(game)

    assert display["line1"] == "MLB"
    assert display["line2"] == "SEA AT SF"
    assert display["line3"] == "POSTPONED"


def test_mlb_optional_context_fields_are_parsed_defensively():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    raw = mlb_game(1, "SF", "SEA", "Live", "2026-07-18T20:00:00Z", 2, 4)
    raw["teams"]["away"].update({
        "leagueRecord": {"wins": 52, "losses": 46},
        "probablePitcher": {"fullName": "Logan Webb"},
    })
    raw["teams"]["home"].update({
        "leagueRecord": {"wins": 54, "losses": 44},
        "probablePitcher": {"fullName": "Bryan Woo"},
    })
    raw.update({
        "venue": {"name": "T-Mobile Park"},
        "broadcasts": [
            {
                "type": "TV",
                "language": "en",
                "name": "ROOT Sports Northwest",
                "callSign": "ROOT",
                "isNational": False,
            },
            {
                "type": "TV",
                "language": "en",
                "name": "FOX",
                "callSign": "FOX",
                "isNational": True,
            },
        ],
        "seriesGameNumber": 2,
        "gamesInSeries": 3,
    })
    raw["linescore"]["offense"] = {"first": {"id": 1}, "third": {"id": 2}}

    game = plugin._parse_mlb_game(raw, timezone.utc)

    assert game["away_record"] == "52-46"
    assert game["home_record"] == "54-44"
    assert game["probable_pitcher_away"] == "Logan Webb"
    assert game["probable_pitcher_home"] == "Bryan Woo"
    assert game["pitching_matchup"] == "Webb / Woo"
    assert game["broadcast"] == "FOX"
    assert game["venue"] == "T-Mobile Park"
    assert game["situation"] == "RUNNERS 1ST 3RD"
    assert game["series_context"] == "GAME 2 OF 3"
    assert plugin._display_fields(game)["context_line"] == "RUNNERS 1ST 3RD"


def test_optional_context_is_empty_when_provider_omits_it():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    game = plugin._parse_mlb_game(
        mlb_game(1, "SEA", "SF", "Preview", "2026-07-18T20:00:00Z", 0, 0),
        timezone.utc,
    )

    for key in (
        "away_record",
        "home_record",
        "venue",
        "broadcast",
        "probable_pitcher_away",
        "probable_pitcher_home",
        "pitching_matchup",
        "situation",
        "series_context",
    ):
        assert game[key] == ""
    assert plugin._display_fields(game)["context_line"] == ""


def test_live_context_compacts_nfl_and_loaded_bases_for_note():
    module = load_plugin_module()

    assert module._compact_situation("RED ZONE 3RD & 4 AT SEA 12", 15) == "RZ 3RD & 4"
    assert module._compact_situation("RUNNERS 1ST 2ND 3RD", 15) == "ON 1ST 2ND 3RD"


def test_context_line_uses_broadcast_only_before_game():
    module = load_plugin_module()
    game = {
        "state": "scheduled",
        "broadcast": "CINR",
        "series_context": "GAME 3 OF 3",
        "away_record": "52-47",
        "home_record": "50-49",
    }

    assert module._context_line(game, 15) == "CINR"
    game["state"] = "live"
    assert module._context_line(game, 15) == "GAME 3 OF 3"
    game["state"] = "final"
    assert module._context_line(game, 15) == "GAME 3 OF 3"


def test_no_match_is_available_but_explicit():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"leagues": ["NFL"], "nfl_teams": ["SEA"], "timezone": "UTC"}
    with patch.object(module.requests, "get", return_value=response({"events": []})):
        result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 0
    assert result.data["line1"] == "SPORTS"
    assert result.data["line2"] == "NO UPCOMING"
    assert result.data["line3"] == "GAMES"
    assert result.data["formatted"] == "NO UPCOMING GAMES"
    assert "NO UPCOMING GAMES" in {line.strip() for line in result.formatted_lines}
    assert set(manifest()["variables"]["simple"]) <= set(result.data)


def test_invalid_timezone_is_reported():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    assert plugin.validate_config({"leagues": ["MLB"], "timezone": "Mars/Olympus"})


def test_malformed_saved_config_returns_a_useful_error():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"leagues": "MLB", "timezone": "UTC", "mlb_teams": "SEA"}
    result = plugin.fetch_data()
    assert not result.available
    assert result.error == "Leagues must be a list; Select at least one league; MLB teams must be a list"


def test_out_of_range_saved_config_is_rejected():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    errors = plugin.validate_config(
        {"leagues": ["MLB"], "timezone": "UTC", "lookahead_days": 30}
    )
    assert errors == ["Upcoming game window must be a whole number from 1 to 14"]


def test_adaptive_refresh_uses_idle_pregame_and_live_tiers():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"refresh_seconds": 600, "live_refresh_seconds": 20}

    assert plugin.refresh_seconds == 600

    upcoming = trigger_game("MLB", "1", "scheduled", "", "")
    upcoming["starts_at"] = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    plugin._cached_results["default"] = sports_result(module, [upcoming])
    assert plugin.refresh_seconds == 60

    plugin._cached_results["default"] = sports_result(
        module,
        [trigger_game("MLB", "1", "live", "1", "0")],
    )
    assert plugin.refresh_seconds == 20


def test_score_change_fires_notable_trigger_once():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"trigger_on_score": True, "trigger_duration_seconds": 45}
    before = trigger_result(module, "live", "1", "0")
    after = trigger_result(module, "live", "2", "0")
    with patch.object(plugin, "get_data", side_effect=[before, after, after]):
        assert plugin.check_triggers() == []
        triggers = plugin.check_triggers()
        assert len(triggers) == 1
        assert triggers[0].trigger_id == "score_mlb-1_2_0"
        assert triggers[0].priority == 50
        assert triggers[0].duration_seconds == 45
        assert triggers[0].data["event"] == "score"
        assert plugin.check_triggers() == []


def test_final_change_fires_trigger():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"trigger_on_final": True}
    before = trigger_result(module, "live", "4", "2")
    after = trigger_result(module, "final", "4", "2")
    with patch.object(plugin, "get_data", side_effect=[before, after]):
        assert plugin.check_triggers() == []
        trigger = plugin.check_triggers()[0]
    assert trigger.trigger_id == "final_mlb-1"
    assert trigger.data["line1"] == "MLB"
    assert trigger.data["line3"] == "FINAL"


def test_game_start_alerts_are_enabled_when_setting_is_absent():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {}
    before = trigger_result(module, "scheduled", "", "")
    after = trigger_result(module, "live", "0", "0")
    with patch.object(plugin, "get_data", side_effect=[before, after]):
        assert plugin.check_triggers() == []
        trigger = plugin.check_triggers()[0]
    assert trigger.trigger_id == "started_mlb-1"
    assert trigger.data["event"] == "started"


def test_overlapping_leagues_keep_independent_trigger_snapshots():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"trigger_on_score": True}
    mlb_before = trigger_game("MLB", "1", "live", "1", "0")
    nfl_before = trigger_game("NFL", "1", "live", "7", "0")
    mlb_after = trigger_game("MLB", "1", "live", "2", "0")
    nfl_after = trigger_game("NFL", "1", "live", "7", "0")
    before = sports_result(module, [mlb_before, nfl_before])
    after = sports_result(module, [mlb_after, nfl_after])

    with patch.object(plugin, "get_data", side_effect=[before, after]):
        assert plugin.check_triggers() == []
        triggers = plugin.check_triggers()

    assert [trigger.trigger_id for trigger in triggers] == ["score_mlb-1_2_0"]


def test_score_line_preserves_both_large_scores():
    module = load_plugin_module()
    line = module._score_line(
        {
            "away_team": "LAFC",
            "away_score": "123",
            "home_team": "VAN",
            "home_score": "123",
        },
        15,
    )
    assert line == "LAFC123 VAN123"
    assert len(line) == 14


def test_colored_team_line_falls_back_when_tiles_do_not_fit():
    module = load_plugin_module()
    line = module._team_line(
        {
            "state": "live",
            "away_team": "LAFC",
            "away_score": "123",
            "home_team": "VAN",
            "home_score": "123",
            "away_team_color": "{67}",
            "home_team_color": "{66}",
        },
        15,
    )

    assert line == "LAFC123 VAN123"
    assert module._tile_count(line) == 14


def test_every_selectable_team_has_a_valid_identity_color():
    module = load_plugin_module()
    settings = manifest()["settings_schema"]["properties"]
    expected = {
        "MLB": set(settings["mlb_teams"]["items"]["enum"]),
        "NFL": set(settings["nfl_teams"]["items"]["enum"]),
    }

    assert set(module.TEAM_COLORS) == set(expected)
    for league, teams in expected.items():
        assert set(module.TEAM_COLORS[league]) == teams
        assert set(module.TEAM_COLORS[league].values()) <= {
            "{63}",
            "{64}",
            "{65}",
            "{66}",
            "{67}",
            "{68}",
            "{69}",
        }


def test_optional_accent_line_is_symmetric_and_note_safe():
    module = load_plugin_module()
    line = module._accent_line({"league": "MLB", "league_color": "{67}"})

    assert line == "{67} MLB {67}"
    assert module._tile_count(line) == 7


def test_one_provider_can_fail_without_hiding_another_league():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"leagues": ["MLB", "NFL"], "timezone": "UTC"}
    game = trigger_game("MLB", "1", "live", "2", "0")
    with patch.object(
        plugin,
        "_fetch_league",
        side_effect=[[game], RuntimeError("scoreboard unavailable")],
    ):
        result = plugin.fetch_data()
    assert result.available
    assert result.data["league"] == "MLB"


def test_invalid_provider_json_is_reported():
    module = load_plugin_module()
    invalid = response({})
    invalid.json.side_effect = ValueError("bad json")
    with patch.object(module.requests, "get", return_value=invalid):
        with pytest.raises(module.SportsDataError, match="NFL returned invalid JSON"):
            module._request_json("https://example.test", {}, "NFL")


def trigger_result(module, state, away_score, home_score):
    return sports_result(module, [trigger_game("MLB", "mlb-1", state, away_score, home_score)])


def trigger_game(league, event_id, state, away_score, home_score):
    return {
        "league": league,
        "event_id": event_id,
        "away_team": "SEA",
        "home_team": "SF",
        "away_score": away_score,
        "home_score": home_score,
        "state": state,
        "status": "FINAL" if state == "final" else "BOT 7 1 OUT",
        "starts_at": "2026-07-13T20:00:00+00:00",
        "minutes_until_start": -1,
    }


def sports_result(module, games):
    game = games[0]
    return module.PluginResult(
        available=True,
        data={
            **game,
            "game_count": len(games),
            "has_live_game": any(item["state"] == "live" for item in games),
            "games": games,
        },
    )


def mlb_game(game_id, away, home, state, starts_at, away_score, home_score):
    return {
        "gamePk": game_id,
        "gameDate": starts_at,
        "status": {"abstractGameState": state, "detailedState": state},
        "teams": {
            "away": {"team": {"abbreviation": away}, "score": away_score},
            "home": {"team": {"abbreviation": home}, "score": home_score},
        },
        "linescore": {"currentInning": 7, "inningHalf": "Bottom", "outs": 1},
    }


def nfl_game(away, home, starts_at):
    return {
        "id": "nfl-1",
        "date": starts_at,
        "competitions": [{
            "competitors": [
                {
                    "homeAway": "away",
                    "score": "0",
                    "team": {"abbreviation": away},
                    "records": [{"name": "overall", "summary": "14-3"}],
                },
                {
                    "homeAway": "home",
                    "score": "0",
                    "team": {"abbreviation": home},
                    "records": [{"name": "overall", "summary": "12-5"}],
                },
            ],
            "venue": {"fullName": "Lumen Field"},
            "broadcasts": [{"market": "national", "names": ["NBC"]}],
            "notes": [{"headline": "Sunday Night Football"}],
            "status": {
                "period": 0,
                "displayClock": "0:00",
                "type": {"state": "pre", "completed": False, "shortDetail": "Scheduled"},
            },
        }],
    }
