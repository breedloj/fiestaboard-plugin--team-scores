from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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
    assert manifest()["version"] == "1.0.0"


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
    with patch.object(module.requests, "get", return_value=response(payload)), patch.object(
        plugin, "_now", return_value=datetime(2026, 7, 13, 12, tzinfo=timezone.utc)
    ):
        with plugin._bound_board(SimpleNamespace(device_type="note")):
            result = plugin.fetch_data()

    assert result.available
    assert result.data["league"] == "NFL"
    assert result.data["line2"] == "SEA AT SF"
    assert all(len(line) <= 15 for line in result.formatted_lines[:3])


def test_no_match_is_available_but_explicit():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    plugin.config = {"leagues": ["NFL"], "nfl_teams": ["SEA"], "timezone": "UTC"}
    with patch.object(module.requests, "get", return_value=response({"events": []})):
        result = plugin.fetch_data()
    assert result.available
    assert result.data["game_count"] == 0
    assert result.data["line2"] == "NO MATCHED GAME"


def test_invalid_timezone_is_reported():
    module = load_plugin_module()
    plugin = module.Plugin(manifest())
    assert plugin.validate_config({"leagues": ["MLB"], "timezone": "Mars/Olympus"})


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
            "status": {"period": 0, "displayClock": "0:00", "type": {"state": "pre", "completed": False, "shortDetail": "Scheduled"}},
        }],
    }
