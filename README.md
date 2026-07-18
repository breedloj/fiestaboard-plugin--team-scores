# Favorite Sports for FiestaBoard

An installable FiestaBoard plugin for MLB and NFL scores centered on favorite teams instead of arbitrary league-wide games.

![Favorite Sports on a Vestaboard Note](./docs/board-display.png)

## Highlights

- MLB schedules and scores from the official MLB Stats API
- NFL schedules and scores from ESPN's public scoreboard feed
- Separate favorite-team selectors for MLB and NFL
- Relevance order: live games, recent finals, then upcoming games
- Configurable final-score retention and upcoming-game window
- Variable-mode timing through `minutes_until_start`
- Optional start, score, and final triggers that briefly interrupt the normal rotation
- Independent trigger tracking when multiple leagues overlap
- Three ready-to-display fields designed for the 15x3 Vestaboard Note
- No API key required

## Install

Install the repository's HTTPS URL from FiestaBoard's **Integrations** page:

```text
https://github.com/breedloj/fiestaboard-plugin--favorite-sports
```

No API key is required.

## Template Variables

### Primary Game

| Variable | Description | Example |
|---|---|---|
| `{{favorite_sports.league}}` | League for the most relevant game | `MLB` |
| `{{favorite_sports.state}}` | `scheduled`, `live`, `final`, or `none` | `live` |
| `{{favorite_sports.away_team}}` | Away-team abbreviation | `SEA` |
| `{{favorite_sports.home_team}}` | Home-team abbreviation | `SF` |
| `{{favorite_sports.away_score}}` | Away score when available | `4` |
| `{{favorite_sports.home_score}}` | Home score when available | `2` |
| `{{favorite_sports.status}}` | Start time, live detail, or final status | `BOT 7 1 OUT` |
| `{{favorite_sports.minutes_until_start}}` | Minutes until a scheduled game, otherwise `-1` | `30` |
| `{{favorite_sports.games}}` | Relevant games ordered by live, recent final, then upcoming | array |

### Ready-to-Display

| Variable | Description | Maximum |
|---|---|---|
| `{{favorite_sports.line1}}` | Note-ready league and state | 15 tiles |
| `{{favorite_sports.line2}}` | Note-ready matchup or score | 15 tiles |
| `{{favorite_sports.line3}}` | Note-ready time or game detail | 15 tiles |
| `{{favorite_sports.formatted}}` | Compact primary game for Flagship templates | 22 tiles |

## Note Template

```text
{{favorite_sports.line1}}
{{favorite_sports.line2}}
{{favorite_sports.line3}}
```

Example live game:

```text
MLB LIVE
SEA 4  SF 2
BOT 7 1 OUT
```

Example upcoming NFL game:

```text
NFL SCHEDULED
SEA AT SF
SUN 1:25 PM
```

## Selection Behavior

Configure MLB and NFL favorites independently in the FiestaBoard UI. If a league's favorite list is empty, all games from that league are eligible. The primary fields always describe the highest-ranked relevant game.

Use `favorite_sports.state` and `favorite_sports.minutes_until_start` for collection rules. Start, score, and final changes are better handled by FiestaBoard triggers: enable the alert types, choose **Favorite Sports for Note** as the trigger page, and the normal page or collection resumes when the alert expires. Each league's event identifiers are tracked independently during the MLB/NFL overlap.

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
| Refresh Interval | 120 seconds | Provider polling interval |

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
