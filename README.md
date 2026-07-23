# Team Scores for FiestaBoard

An installable FiestaBoard plugin for MLB and NFL scores centered on favorite teams instead of arbitrary league-wide games.

![Team Scores on a Vestaboard Note](./docs/board-display.png)

## Highlights

- MLB schedules and scores from the official MLB Stats API
- NFL schedules and scores from ESPN's public scoreboard feed
- Separate favorite-team selectors for MLB and NFL
- Relevance order: live games, recent finals, then upcoming games
- Configurable final-score retention and upcoming-game window
- Variable-mode timing through `minutes_until_start`
- Optional start, score, and final triggers that briefly interrupt the normal rotation
- Adaptive polling: 10 minutes when idle, 60 seconds before games, and 30 seconds live
- Independent trigger tracking when multiple leagues overlap
- Three ready-to-display fields designed for the 15x3 Vestaboard Note
- Curated MLB and NFL identity colors mapped to Vestaboard's tile palette
- Optional broadcast, records, venue, pitcher, series, and live-situation variables
- No API key required

## Install

Install the repository's HTTPS URL from FiestaBoard's **Integrations** page:

```text
https://github.com/breedloj/fiestaboard-plugin--team-scores
```

No API key is required.

## Template Variables

### Primary Game

| Variable | Description | Example |
|---|---|---|
| `{{team_scores.league}}` | League for the most relevant game | `MLB` |
| `{{team_scores.state}}` | `scheduled`, `live`, `final`, or `none` | `live` |
| `{{team_scores.away_team}}` | Away-team abbreviation | `SEA` |
| `{{team_scores.home_team}}` | Home-team abbreviation | `SF` |
| `{{team_scores.away_score}}` | Away score when available | `4` |
| `{{team_scores.home_score}}` | Home score when available | `2` |
| `{{team_scores.status}}` | Start time, live detail, or final status | `BOT 7 1 OUT` |
| `{{team_scores.minutes_until_start}}` | Minutes until a scheduled game, otherwise `-1` | `30` |
| `{{team_scores.games}}` | Relevant games ordered by live, recent final, then upcoming | array |

### Optional Context

These values are empty when a provider does not supply them. They are also available on every item in `team_scores.games`.

| Variable | Description | Example |
|---|---|---|
| `{{team_scores.away_record}}` | Away-team season record | `52-46` |
| `{{team_scores.home_record}}` | Home-team season record | `54-44` |
| `{{team_scores.away_team_color}}` | Away-team identity color tile | `{64}` |
| `{{team_scores.home_team_color}}` | Home-team identity color tile | `{66}` |
| `{{team_scores.league_color}}` | League accent color tile | `{67}` |
| `{{team_scores.broadcast}}` | Preferred TV broadcaster | `ROOT SPORTS` |
| `{{team_scores.venue}}` | Venue name | `T-Mobile Park` |
| `{{team_scores.probable_pitcher_away}}` | MLB away probable pitcher | `Logan Webb` |
| `{{team_scores.probable_pitcher_home}}` | MLB home probable pitcher | `Bryan Woo` |
| `{{team_scores.pitching_matchup}}` | Compact MLB pitching matchup | `Webb / Woo` |
| `{{team_scores.situation}}` | MLB occupied bases or NFL down-and-distance | `RUNNERS 1ST 3RD` |
| `{{team_scores.series_context}}` | MLB series game or NFL event label | `GAME 2 OF 3` |

### Ready-to-Display

| Variable | Description | Maximum |
|---|---|---|
| `{{team_scores.line1}}` | Note-ready sports header | 15 tiles |
| `{{team_scores.line2}}` | Note-ready matchup or score | 15 tiles |
| `{{team_scores.line3}}` | Note-ready time or game detail | 15 tiles |
| `{{team_scores.team_line}}` | Matchup or score with team identity tiles | 15 tiles |
| `{{team_scores.accent_line1}}` | Optional league header with symmetric accents | 7 tiles |
| `{{team_scores.context_line}}` | Best available optional context | 15 tiles |
| `{{team_scores.formatted}}` | Compact primary game for Flagship templates | 22 tiles |

## Note Template

```text
{{team_scores.line1}}
{{team_scores.team_line}}
{{team_scores.line3}}
```

Center rows one and three and left-align row two. Team colors are manually curated to the closest representative Vestaboard color rather than calculated from provider data. Existing `away_color` and `home_color` variables remain result indicators and are not changed.

Example live game:

```text
MLB
{66}SEA 4 {64}SF 2
BOT 7 1 OUT
```

Example final:

```text
MLB
{63}CIN 5 {66}SEA 3
FINAL
```

Example upcoming NFL game:

```text
NFL
{66}SEA AT {63}SF
SUN 1:25 PM
```

When no configured team has an eligible game:

```text
SPORTS
NO UPCOMING
GAMES
```

For a slightly more decorative first row, replace `line1` with `accent_line1`. The default remains the plain league header so the Note does not become overly colorful.

`context_line` is intentionally separate so the default page remains stable. Pregame it prefers the broadcaster, pitching matchup, records, series context, or venue. Live it prefers the current base or down-and-distance situation. After a final it prefers series context, records, or venue, so stale broadcast information does not linger. It can be used on an alternate context page without changing the score page.

## Selection Behavior

Configure MLB and NFL favorites independently in the FiestaBoard UI. If a league's favorite list is empty, all games from that league are eligible. The primary fields always describe the highest-ranked relevant game.

Use `team_scores.state` and `team_scores.minutes_until_start` for collection rules. Start, score, and final changes are better handled by FiestaBoard triggers: enable the alert types, choose **Team Scores for Note** as the trigger page, and the normal page or collection resumes when the alert expires. Each league's event identifiers are tracked independently during the MLB/NFL overlap.

## Configuration

| Setting | Default | Description |
|---|---:|---|
| Leagues | MLB and NFL | Enable either league or both |
| Favorite MLB Teams | All teams | Limit MLB games to selected teams |
| Favorite NFL Teams | All teams | Limit NFL games to selected teams |
| Timezone | America/Los_Angeles | Timezone used for scheduled game times |
| Upcoming Game Window | 7 days | How far ahead scheduled games remain eligible |
| Keep Final Scores | 12 hours | How long completed games remain eligible |
| Score Alerts | On | Trigger when a live score changes |
| Final Alerts | On | Trigger when a game becomes final |
| Game Start Alerts | On | Trigger when a scheduled game becomes live |
| Idle Refresh Interval | 600 seconds | Used when no game is live or starting within 30 minutes |
| Live Refresh Interval | 30 seconds | Used while a matching game is live; configurable down to 15 seconds |

During the final 30 minutes before a scheduled game, the plugin automatically refreshes every 60 seconds. Once a matching game becomes live it switches to the configured live interval, then returns to the idle interval after the game becomes final.

See [docs/SETUP.md](docs/SETUP.md) for configuration details.

## Data Notes

The MLB Stats API is an official public feed. ESPN's NFL scoreboard endpoint is public but undocumented, so its contract is isolated behind a league-driven adapter and covered by mocked tests. This boundary is designed so additional ESPN-backed leagues can reuse the same lifecycle, filtering, display, and trigger behavior.

This plugin complements FiestaBoard's general Sports Scores plugin: it adds MLB, explicit MLB/NFL favorite-team selectors, Note-first formatting, relevance windows, and score/start/final triggers.

## Development

Run tests from a FiestaBoard checkout by setting `FIESTABOARD_ROOT`:

```bash
FIESTABOARD_ROOT=/path/to/FiestaBoard pytest
```

## Author

Jonathan Breedlove
