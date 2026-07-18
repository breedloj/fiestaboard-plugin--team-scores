from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "favorite_sports_external",
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
    assert plugin.plugin_id == "favorite_sports"
    assert manifest()["version"] == "1.2.0"
    assert manifest()["settings_schema"]["properties"]["trigger_on_started"]["default"] is True


def test_fiestaboard_loader_accepts_standalone_repo(tmp_path):
    from src.plugins.loader import PluginLoader

    (tmp_path / "favorite_sports").symlink_to(ROOT, target_is_directory=True)
    loader = PluginLoader(plugins_dir=tmp_path, external_dirs=[])
    plugin = loader.load_plugin("favorite_sports")
    assert plugin is not None, loader._load_errors.get("favorite_sports")


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
    with patch.object(module.requests, "get", return_value=response(payload)), patch.object(
        plugin, "_now", return_value=datetime(2026, 7, 13, 21, tzinfo=timezone.utc)
    ):
        result = plugin.fetch_data()

    assert result.available
    assert result.data["game_count"] == 1
    assert result.data["away_team"] == "SEA"
    assert result.data["state"] == "live"
    assert len(result.data["line2"]) <= 15


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
    assert result.data["line2"] == "SEA AT SF"
    assert all(len(line) <= 15 for line in result.formatted_lines[:3])
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


def test_no_match_is_available_but_explicit():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"leagues": ["NFL"], "nfl_teams": ["SEA"], "timezone": "UTC"}
    with patch.object(module.requests, "get", return_value=response({"events": []})):
        result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 0
    assert result.data["line2"] == "NO MATCHED GAME"
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
                {"homeAway": "away", "score": "0", "team": {"abbreviation": away}},
                {"homeAway": "home", "score": "0", "team": {"abbreviation": home}},
            ],
            "status": {
                "period": 0,
                "displayClock": "0:00",
                "type": {"state": "pre", "completed": False, "shortDetail": "Scheduled"},
            },
        }],
    }
