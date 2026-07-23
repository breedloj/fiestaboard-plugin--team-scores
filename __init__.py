"""Favorite-team MLB and NFL scores for FiestaBoard."""

from __future__ import annotations

import logging
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from src.plugins.base import PluginBase, PluginResult, TriggerResult
from src.triggers import TriggerPriority

logger = logging.getLogger(__name__)

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
REQUEST_TIMEOUT = 20
DEFAULT_IDLE_REFRESH_SECONDS = 600
DEFAULT_LIVE_REFRESH_SECONDS = 30
PREGAME_REFRESH_SECONDS = 60
PREGAME_WINDOW = timedelta(minutes=30)
SUPPORTED_LEAGUES = ("MLB", "NFL")
ESPN_LEAGUES = {
    "NFL": {
        "url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "teams_config": "nfl_teams",
        "period_prefix": "Q",
    },
}


class SportsDataError(RuntimeError):
    """A league provider could not return usable scoreboard data."""


class TeamScoresPlugin(PluginBase):
    """Show the most relevant game involving a configured favorite team."""

    def __init__(self, manifest: dict[str, Any]):
        super().__init__(manifest)
        self._trigger_lock = threading.Lock()
        self._trigger_snapshot: dict[str, dict[str, str]] = {}

    @property
    def plugin_id(self) -> str:
        return "team_scores"

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        raw_leagues = config.get("leagues", list(SUPPORTED_LEAGUES))
        if not isinstance(raw_leagues, list):
            errors.append("Leagues must be a list")
            leagues: list[str] = []
        else:
            leagues = [str(league).strip().upper() for league in raw_leagues]
        if not leagues:
            errors.append("Select at least one league")
        invalid = sorted(set(leagues) - set(SUPPORTED_LEAGUES))
        if invalid:
            errors.append(f"Unsupported leagues: {', '.join(invalid)}")
        for key, label in (("mlb_teams", "MLB teams"), ("nfl_teams", "NFL teams")):
            if not isinstance(config.get(key, []), list):
                errors.append(f"{label} must be a list")
        for key, label, minimum, maximum in (
            ("lookahead_days", "Upcoming game window", 1, 14),
            ("final_max_age_hours", "Final score retention", 1, 48),
            ("trigger_duration_seconds", "Alert duration", 15, 300),
            ("refresh_seconds", "Idle refresh interval", 120, 3600),
            ("live_refresh_seconds", "Live refresh interval", 15, 60),
        ):
            error = _integer_setting_error(config, key, label, minimum, maximum)
            if error:
                errors.append(error)
        try:
            ZoneInfo(str(config.get("timezone", "UTC")))
        except ZoneInfoNotFoundError:
            errors.append("Timezone must be a valid IANA name, such as America/Los_Angeles")
        return errors

    @property
    def refresh_seconds(self) -> int:
        """Select a cache interval from the most recently fetched game state."""
        idle_interval = _bounded_int(
            self.config.get("refresh_seconds"),
            DEFAULT_IDLE_REFRESH_SECONDS,
            120,
            3600,
        )
        live_interval = _bounded_int(
            self.config.get("live_refresh_seconds"),
            DEFAULT_LIVE_REFRESH_SECONDS,
            15,
            60,
        )
        with self._cache_lock:
            cached_results = list(self._cached_results.values())

        games = [
            game
            for result in cached_results
            if result.available and result.data
            for game in result.data.get("games", [])
        ]
        if any(game.get("state") == "live" for game in games):
            return live_interval

        now = datetime.now(timezone.utc)
        for game in games:
            if game.get("state") != "scheduled":
                continue
            starts_at = _parse_datetime(game.get("starts_at"), timezone.utc)
            if starts_at and starts_at - now <= PREGAME_WINDOW:
                return PREGAME_REFRESH_SECONDS
        return idle_interval

    def fetch_data(self) -> PluginResult:
        validation_errors = self.validate_config(self.config)
        if validation_errors:
            return PluginResult(available=False, error="; ".join(validation_errors))

        tz = self._timezone()
        now = self._now(tz)
        leagues = [
            str(league).strip().upper()
            for league in self.config.get("leagues", list(SUPPORTED_LEAGUES))
        ]
        lookahead_days = max(1, min(14, int(self.config.get("lookahead_days", 7))))
        final_max_age = timedelta(hours=max(1, float(self.config.get("final_max_age_hours", 12))))
        games: list[dict[str, Any]] = []
        errors: list[str] = []

        for league in leagues:
            try:
                games.extend(self._fetch_league(league, now, lookahead_days))
            except Exception as exc:
                # Keep one provider failure from hiding another selected league.
                logger.exception("%s fetch failed", league)
                errors.append(f"{league}: {exc}")

        games = [game for game in games if self._is_relevant(game, now, lookahead_days, final_max_age)]
        for game in games:
            game["minutes_until_start"] = _minutes_until_start(game, now)
        games.sort(key=self._sort_key)

        if not games:
            if errors:
                return PluginResult(available=False, error="; ".join(errors))
            data = self._empty_data()
            return PluginResult(available=True, data=data, formatted_lines=self._format_display(data))

        primary = games[0]
        data = self._result_data(primary, games)
        return PluginResult(available=True, data=data, formatted_lines=self._format_display(data))

    def check_triggers(self) -> list[TriggerResult]:
        result = self.get_data()
        if not result.available or not result.data:
            return []

        games = result.data.get("games", [])
        current = {
            _event_key(game): _trigger_state(game)
            for game in games
            if game.get("event_id")
        }
        with self._trigger_lock:
            previous = self._trigger_snapshot
            self._trigger_snapshot = current

        if not previous:
            return []

        duration = max(15, min(300, int(self.config.get("trigger_duration_seconds", 45))))
        triggers: list[TriggerResult] = []
        for game in games:
            before = previous.get(_event_key(game))
            if before is None:
                continue
            event = self._detect_event(before, game)
            if event == "none" or not self.config.get(f"trigger_on_{event}", True):
                continue
            data = self._result_data(game, games, event=event)
            triggers.append(
                TriggerResult(
                    triggered=True,
                    trigger_id=_trigger_id(event, game),
                    priority=TriggerPriority.NOTABLE,
                    duration_seconds=duration,
                    data=data,
                    message=data["formatted"],
                )
            )
        return triggers

    def on_config_change(self, old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
        with self._trigger_lock:
            self._trigger_snapshot = {}

    @staticmethod
    def _detect_event(before: dict[str, str], game: dict[str, Any]) -> str:
        state = str(game.get("state", ""))
        if state == "final" and before["state"] != "final":
            return "final"
        if state == "live" and before["state"] == "scheduled":
            return "started"
        scores = (str(game.get("away_score", "")), str(game.get("home_score", "")))
        if state == "live" and scores != (before["away_score"], before["home_score"]):
            return "score"
        return "none"

    def _result_data(
        self,
        primary: dict[str, Any],
        games: list[dict[str, Any]],
        event: str = "none",
    ) -> dict[str, Any]:
        data = {
            **primary,
            "event": event,
            "game_count": len(games),
            "has_live_game": any(game["state"] == "live" for game in games),
            "games": games,
        }
        data.update(self._display_fields(primary))
        return data

    def _fetch_mlb(self, now: datetime, lookahead_days: int) -> list[dict[str, Any]]:
        params = {
            "sportId": 1,
            "startDate": (now.date() - timedelta(days=1)).isoformat(),
            "endDate": (now.date() + timedelta(days=lookahead_days)).isoformat(),
            "hydrate": "team,linescore,probablePitcher,venue,broadcasts",
        }
        payload = _request_json(MLB_SCHEDULE_URL, params, "MLB")
        favorites = {str(team).strip().upper() for team in self.config.get("mlb_teams", [])}
        games: list[dict[str, Any]] = []
        date_groups = payload.get("dates", [])
        if not isinstance(date_groups, list):
            raise SportsDataError("MLB returned an unexpected schedule")
        for date_group in date_groups:
            if not isinstance(date_group, dict):
                continue
            for raw in date_group.get("games", []):
                if not isinstance(raw, dict):
                    continue
                game = self._parse_mlb_game(raw, now.tzinfo)
                if not favorites or {game["away_team"], game["home_team"]} & favorites:
                    games.append(game)
        return games

    def _fetch_league(
        self,
        league: str,
        now: datetime,
        lookahead_days: int,
    ) -> list[dict[str, Any]]:
        if league == "MLB":
            return self._fetch_mlb(now, lookahead_days)
        return self._fetch_espn(league, now, lookahead_days)

    def _fetch_espn(
        self,
        league: str,
        now: datetime,
        lookahead_days: int,
    ) -> list[dict[str, Any]]:
        spec = ESPN_LEAGUES[league]
        params = {
            "dates": (
                f"{(now.date() - timedelta(days=1)).strftime('%Y%m%d')}-"
                f"{(now.date() + timedelta(days=lookahead_days)).strftime('%Y%m%d')}"
            )
        }
        payload = _request_json(str(spec["url"]), params, league)
        favorites = {
            str(team).strip().upper()
            for team in self.config.get(str(spec["teams_config"]), [])
        }
        games: list[dict[str, Any]] = []
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise SportsDataError(f"{league} returned an unexpected scoreboard")
        for event in events:
            if not isinstance(event, dict):
                continue
            game = self._parse_espn_game(event, now.tzinfo, league)
            if game and (not favorites or {game["away_team"], game["home_team"]} & favorites):
                games.append(game)
        return games

    def _parse_mlb_game(self, raw: dict[str, Any], tz: Any) -> dict[str, Any]:
        teams = raw.get("teams", {})
        away = teams.get("away", {})
        home = teams.get("home", {})
        status = raw.get("status", {})
        abstract = str(status.get("abstractGameState", "Preview")).lower()
        detailed_status = str(status.get("detailedState", ""))
        state = _mlb_state(abstract, detailed_status)
        starts_at = _parse_datetime(raw.get("gameDate"), tz)
        away_team = _mlb_abbreviation(away.get("team", {}), "AWAY")
        home_team = _mlb_abbreviation(home.get("team", {}), "HOME")
        probable_pitcher_away = _person_name(away.get("probablePitcher"))
        probable_pitcher_home = _person_name(home.get("probablePitcher"))
        detail = (
            _mlb_detail(raw)
            if state == "live"
            else "FINAL"
            if state == "final"
            else _scheduled_status(detailed_status, starts_at)
        )
        return _game(
            league="MLB",
            event_id=str(raw.get("gamePk", "")),
            away_team=away_team,
            home_team=home_team,
            away_score=_score(away, state),
            home_score=_score(home, state),
            state=state,
            status=detail,
            detailed_status=detailed_status,
            starts_at=starts_at,
            away_record=_record(away.get("leagueRecord")),
            home_record=_record(home.get("leagueRecord")),
            venue=_nested_text(raw, "venue", "name"),
            broadcast=_mlb_broadcast(raw.get("broadcasts")),
            probable_pitcher_away=probable_pitcher_away,
            probable_pitcher_home=probable_pitcher_home,
            pitching_matchup=_pitching_matchup(probable_pitcher_away, probable_pitcher_home),
            situation=_mlb_situation(raw),
            series_context=_mlb_series_context(raw),
        )

    def _parse_espn_game(
        self,
        event: dict[str, Any],
        tz: Any,
        league: str,
    ) -> dict[str, Any] | None:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            return None
        away = _competitor(competitors, "away")
        home = _competitor(competitors, "home")
        status = competition.get("status", {})
        status_type = status.get("type", {})
        state = (
            "final"
            if status_type.get("completed")
            else "live"
            if status_type.get("state") == "in"
            else "scheduled"
        )
        starts_at = _parse_datetime(event.get("date"), tz)
        detail = (
            _espn_detail(status, str(ESPN_LEAGUES[league]["period_prefix"]))
            if state == "live"
            else "FINAL"
            if state == "final"
            else _scheduled_status(str(status_type.get("description", "")), starts_at)
        )
        return _game(
            league=league,
            event_id=str(event.get("id", "")),
            away_team=away["team"],
            home_team=home["team"],
            away_score=away["score"] if state != "scheduled" else "",
            home_score=home["score"] if state != "scheduled" else "",
            state=state,
            status=detail,
            detailed_status=str(status_type.get("shortDetail", "")),
            starts_at=starts_at,
            away_record=away["record"],
            home_record=home["record"],
            venue=_nested_text(competition, "venue", "fullName"),
            broadcast=_espn_broadcast(competition.get("broadcasts")),
            situation=_espn_situation(competition.get("situation")),
            series_context=_espn_event_context(competition.get("notes")),
        )

    def _is_relevant(
        self,
        game: dict[str, Any],
        now: datetime,
        lookahead_days: int,
        final_max_age: timedelta,
    ) -> bool:
        starts_at = _parse_datetime(game.get("starts_at"), now.tzinfo)
        if game["state"] == "live":
            return True
        if starts_at is None:
            return game["state"] != "final"
        if game["state"] == "final":
            return now - starts_at <= final_max_age
        return starts_at <= now + timedelta(days=lookahead_days)

    @staticmethod
    def _sort_key(game: dict[str, Any]) -> tuple[int, float]:
        timestamp = _timestamp(game.get("starts_at"))
        if game["state"] == "live":
            return 0, timestamp
        if game["state"] == "final":
            return 1, -timestamp
        return 2, timestamp

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(str(self.config.get("timezone", "UTC")))
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @staticmethod
    def _now(tz: ZoneInfo) -> datetime:
        return datetime.now(tz)

    def _display_fields(self, game: dict[str, Any]) -> dict[str, str]:
        if game["state"] == "scheduled":
            line2 = f"{game['away_team']} AT {game['home_team']}"
            line3 = game["status"]
        else:
            line2 = _score_line(game, 15)
            line3 = game["status"]
        if game["state"] == "final":
            header = f"{game['league']} SCORES"
        else:
            header = f"{game['league']} {game['state'].upper()}"
        return {
            "header": _fit(header, 22),
            "line1": _fit(game["league"], 15),
            "line2": _fit(line2, 15),
            "line3": _fit(line3, 15),
            "context_line": _context_line(game, 15),
            "formatted": _fit(f"{line2} {line3}", 22),
        }

    def _format_display(self, data: dict[str, Any]) -> list[str]:
        device_type = getattr(self.board, "device_type", "flagship") if self.board else "flagship"
        if device_type == "note":
            return [
                data.get("line1", "SPORTS"),
                data.get("line2", "NO UPCOMING"),
                data.get("line3", "GAMES"),
            ]
        lines = [data.get("header", "SPORTS").center(22)]
        if not data.get("games"):
            lines.append(_fit(data.get("formatted", "NO UPCOMING GAMES"), 22).center(22))
        for game in data.get("games", [])[:2]:
            display = self._display_fields(game)
            lines.extend([_fit(display["line2"], 22), _fit(display["line3"], 22)])
        while len(lines) < 6:
            lines.append("")
        return lines[:6]

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "league": "",
            "event_id": "",
            "away_team": "",
            "home_team": "",
            "away_score": "",
            "home_score": "",
            "away_margin": 0,
            "home_margin": 0,
            "away_color": "",
            "home_color": "",
            "state": "none",
            "status": "NO UPCOMING GAMES",
            "detailed_status": "",
            "starts_at": "",
            "away_record": "",
            "home_record": "",
            "venue": "",
            "broadcast": "",
            "probable_pitcher_away": "",
            "probable_pitcher_home": "",
            "pitching_matchup": "",
            "situation": "",
            "series_context": "",
            "game_count": 0,
            "has_live_game": False,
            "minutes_until_start": -1,
            "event": "none",
            "games": [],
            "header": "SPORTS",
            "line1": "SPORTS",
            "line2": "NO UPCOMING",
            "line3": "GAMES",
            "context_line": "",
            "formatted": "NO UPCOMING GAMES",
        }


def _game(
    *,
    league: str,
    event_id: str,
    away_team: str,
    home_team: str,
    away_score: str,
    home_score: str,
    state: str,
    status: str,
    detailed_status: str,
    starts_at: datetime | None,
    away_record: str = "",
    home_record: str = "",
    venue: str = "",
    broadcast: str = "",
    probable_pitcher_away: str = "",
    probable_pitcher_home: str = "",
    pitching_matchup: str = "",
    situation: str = "",
    series_context: str = "",
) -> dict[str, Any]:
    margin = _margin(away_score, home_score)
    return {
        "league": league,
        "event_id": event_id,
        "away_team": away_team,
        "home_team": home_team,
        "away_score": away_score,
        "home_score": home_score,
        "away_margin": margin,
        "home_margin": -margin,
        "away_color": _team_color(margin, state),
        "home_color": _team_color(-margin, state),
        "state": state,
        "status": status,
        "detailed_status": detailed_status,
        "starts_at": starts_at.isoformat() if starts_at else "",
        "away_record": away_record,
        "home_record": home_record,
        "venue": venue,
        "broadcast": broadcast,
        "probable_pitcher_away": probable_pitcher_away,
        "probable_pitcher_home": probable_pitcher_home,
        "pitching_matchup": pitching_matchup,
        "situation": situation,
        "series_context": series_context,
    }


def _minutes_until_start(game: dict[str, Any], now: datetime) -> int:
    if game.get("state") != "scheduled":
        return -1
    starts_at = _parse_datetime(game.get("starts_at"), now.tzinfo)
    if starts_at is None:
        return -1
    return max(0, math.ceil((starts_at - now).total_seconds() / 60))


def _trigger_state(game: dict[str, Any]) -> dict[str, str]:
    return {
        "state": str(game.get("state", "")),
        "away_score": str(game.get("away_score", "")),
        "home_score": str(game.get("home_score", "")),
    }


def _trigger_id(event: str, game: dict[str, Any]) -> str:
    event_id = _event_key(game)
    if event == "score":
        return f"score_{event_id}_{game.get('away_score', '')}_{game.get('home_score', '')}"
    return f"{event}_{event_id}"


def _event_key(game: dict[str, Any]) -> str:
    league = str(game.get("league") or "game").strip().lower()
    event_id = str(game.get("event_id") or "game").strip()
    prefix = f"{league}-"
    return event_id if event_id.lower().startswith(prefix) else f"{prefix}{event_id}"


def _mlb_abbreviation(team: dict[str, Any], fallback: str) -> str:
    return str(team.get("abbreviation") or team.get("teamCode") or team.get("name") or fallback).upper()


def _mlb_state(abstract: str, detailed: str) -> str:
    if abstract == "final":
        return "final"
    if abstract != "live":
        return "scheduled"
    normalized = detailed.strip().lower().replace("-", " ")
    if normalized in {"warmup", "pre game", "pregame"}:
        return "scheduled"
    return "live"


def _score(side: dict[str, Any], state: str) -> str:
    if state == "scheduled":
        return ""
    value = side.get("score")
    return "0" if value is None else str(value)


def _competitor(items: list[dict[str, Any]], side: str) -> dict[str, str]:
    item = next((entry for entry in items if entry.get("homeAway") == side), items[0])
    team = item.get("team", {})
    return {
        "team": str(team.get("abbreviation") or team.get("shortDisplayName") or side).upper(),
        "score": str(item.get("score") or "0"),
        "record": _espn_record(item.get("records")),
    }


def _record(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    wins = value.get("wins")
    losses = value.get("losses")
    if wins is None or losses is None:
        return ""
    ties = value.get("ties")
    suffix = f"-{ties}" if ties not in {None, 0, "0"} else ""
    return f"{wins}-{losses}{suffix}"


def _espn_record(records: Any) -> str:
    if not isinstance(records, list):
        return ""
    overall = next(
        (record for record in records if str(record.get("name", "")).lower() == "overall"),
        records[0] if records else {},
    )
    return str(overall.get("summary") or "") if isinstance(overall, dict) else ""


def _person_name(value: Any) -> str:
    return str(value.get("fullName") or "") if isinstance(value, dict) else ""


def _pitching_matchup(away: str, home: str) -> str:
    if not away or not home:
        return away or home
    return f"{away.rsplit(' ', 1)[-1]} / {home.rsplit(' ', 1)[-1]}"


def _nested_text(value: Any, *keys: str) -> str:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")


def _mlb_broadcast(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    tv = [
        item
        for item in value
        if isinstance(item, dict)
        and item.get("type") == "TV"
        and item.get("language", "en") == "en"
    ]
    if not tv:
        return ""
    preferred = next((item for item in tv if item.get("isNational")), tv[0])
    return str(preferred.get("name") or preferred.get("callSign") or "")


def _espn_broadcast(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if not isinstance(item, dict):
            continue
        names = item.get("names")
        if isinstance(names, list) and names:
            return str(names[0])
    return ""


def _mlb_situation(raw: dict[str, Any]) -> str:
    offense = raw.get("linescore", {}).get("offense", {})
    if not isinstance(offense, dict):
        return ""
    occupied = [
        label
        for key, label in (("first", "1ST"), ("second", "2ND"), ("third", "3RD"))
        if offense.get(key)
    ]
    if not occupied:
        return ""
    prefix = "RUNNER" if len(occupied) == 1 else "RUNNERS"
    return f"{prefix} {' '.join(occupied)}"


def _espn_situation(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    detail = str(value.get("shortDownDistanceText") or value.get("downDistanceText") or "")
    if value.get("isRedZone") and detail:
        return f"RED ZONE {detail}".upper()
    return detail.upper()


def _mlb_series_context(raw: dict[str, Any]) -> str:
    number = raw.get("seriesGameNumber")
    total = raw.get("gamesInSeries")
    if number and total:
        return f"GAME {number} OF {total}"
    return str(raw.get("seriesDescription") or "")


def _espn_event_context(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    first = next((item for item in value if isinstance(item, dict) and item.get("headline")), None)
    return str(first.get("headline") or "") if first else ""


def _context_line(game: dict[str, Any], width: int) -> str:
    state = game.get("state")
    if state == "live" and game.get("situation"):
        return _compact_situation(str(game["situation"]), width)
    if state == "scheduled":
        candidates = (
            game.get("broadcast"),
            game.get("pitching_matchup"),
            _record_matchup(game),
            game.get("series_context"),
            game.get("venue"),
        )
    else:
        candidates = (
            game.get("series_context"),
            _record_matchup(game),
            game.get("venue"),
        )
    available = [str(value).strip() for value in candidates if value]
    fallback = _fit(available[0], width) if available else ""
    return next((value for value in available if len(value) <= width), fallback)


def _compact_situation(value: str, width: int) -> str:
    candidates = [value]
    if value.startswith("RED ZONE "):
        candidates.append(f"RZ {value.removeprefix('RED ZONE ')}")
    if value.startswith("RUNNERS "):
        candidates.append(f"ON {value.removeprefix('RUNNERS ')}")
    candidates.extend(
        candidate.split(" AT ", 1)[0]
        for candidate in tuple(candidates)
        if " AT " in candidate
    )
    return next((candidate for candidate in candidates if len(candidate) <= width), _fit(candidates[-1], width))


def _record_matchup(game: dict[str, Any]) -> str:
    away = str(game.get("away_record") or "")
    home = str(game.get("home_record") or "")
    if away and home:
        return f"{away} / {home}"
    return away or home


def _mlb_detail(raw: dict[str, Any]) -> str:
    linescore = raw.get("linescore", {})
    inning = linescore.get("currentInning")
    half = str(linescore.get("inningHalf", "")).upper()
    prefix = {"BOTTOM": "BOT", "MIDDLE": "MID"}.get(half, half[:3])
    parts = [part for part in (prefix, str(inning or "")) if part]
    outs = linescore.get("outs")
    if outs not in {None, ""}:
        parts.extend([str(outs), "OUT" if str(outs) == "1" else "OUTS"])
    return " ".join(parts) or "LIVE"


def _espn_detail(status: dict[str, Any], period_prefix: str) -> str:
    period = status.get("period")
    clock = str(status.get("displayClock", "")).strip()
    parts = [f"{period_prefix}{period}" if period else "LIVE"]
    if clock and clock != "0:00":
        parts.append(clock)
    return " ".join(parts)


def _start_label(starts_at: datetime | None) -> str:
    if not starts_at:
        return "SCHEDULED"
    return starts_at.strftime("%a %I:%M %p").replace(" 0", " ").upper()


def _scheduled_status(detail: str, starts_at: datetime | None) -> str:
    normalized = detail.upper()
    if "POSTPON" in normalized:
        return "POSTPONED"
    if "CANCEL" in normalized:
        return "CANCELLED"
    return _start_label(starts_at)


def _parse_datetime(value: Any, tz: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(tz)


def _timestamp(value: Any) -> float:
    parsed = _parse_datetime(value, timezone.utc)
    return parsed.timestamp() if parsed else 0


def _margin(away: Any, home: Any) -> float:
    try:
        return float(away) - float(home)
    except (TypeError, ValueError):
        return 0


def _team_color(margin: float, state: str) -> str:
    if state == "scheduled":
        return "{67}"
    if margin > 0:
        return "{66}"
    if margin < 0:
        return "{63}"
    return "{65}"


def _score_line(game: dict[str, Any], width: int) -> str:
    away = str(game.get("away_team") or "AWAY")
    home = str(game.get("home_team") or "HOME")
    away_score = str(game.get("away_score") or "0")
    home_score = str(game.get("home_score") or "0")
    candidates = (
        f"{away} {away_score}  {home} {home_score}",
        f"{away} {away_score} {home} {home_score}",
        f"{away}{away_score} {home}{home_score}",
    )
    return next((line for line in candidates if len(line) <= width), _fit(candidates[-1], width))


def _request_json(url: str, params: dict[str, Any], provider: str) -> dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f" (HTTP {status})" if status else ""
        raise SportsDataError(f"{provider} request failed{detail}") from exc
    except ValueError as exc:
        raise SportsDataError(f"{provider} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SportsDataError(f"{provider} returned an unexpected response")
    return payload


def _integer_setting_error(
    config: dict[str, Any],
    key: str,
    label: str,
    minimum: int,
    maximum: int,
) -> str | None:
    if key not in config:
        return None
    value = config[key]
    if isinstance(value, bool):
        return f"{label} must be a whole number from {minimum} to {maximum}"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return f"{label} must be a whole number from {minimum} to {maximum}"
    if not parsed.is_integer() or not minimum <= parsed <= maximum:
        return f"{label} must be a whole number from {minimum} to {maximum}"
    return None


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _fit(value: Any, width: int) -> str:
    return str(value or "").strip()[:width]


Plugin = TeamScoresPlugin
