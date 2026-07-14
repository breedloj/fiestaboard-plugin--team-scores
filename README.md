# Favorite Sports for FiestaBoard

An installable FiestaBoard plugin for MLB and NFL scores centered on favorite teams instead of arbitrary league-wide games.

## Highlights

- MLB schedules and scores from the official MLB Stats API
- NFL schedules and scores from ESPN's public scoreboard feed
- Separate favorite-team selectors for MLB and NFL
- Relevance order: live games, recent finals, then upcoming games
- Configurable final-score retention and upcoming-game window
- Variable-mode timing through `minutes_until_start`
- Optional score and final triggers that briefly interrupt the normal rotation
- Three ready-to-display fields designed for the 15x3 Vestaboard Note
- No API key required

## Install

After this directory is pushed to a public GitHub repository, install its HTTPS URL from FiestaBoard's Integrations page. The repository name should remain `fiestaboard-plugin--favorite-sports` if it may eventually be submitted to the FiestaBoard registry.

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

Use `favorite_sports.state` and `favorite_sports.minutes_until_start` for collection rules. Score and final changes are better handled by FiestaBoard triggers: enable the alert types, choose **Favorite Sports for Note** as the trigger page, and the normal page or collection resumes when the alert expires.

See [docs/SETUP.md](docs/SETUP.md) for configuration details.

## Data Notes

The MLB Stats API is an official public feed. ESPN's NFL scoreboard endpoint is public but undocumented, so its adapter is intentionally isolated and covered by mocked contract tests.

## Development

Run tests from a FiestaBoard checkout by setting `FIESTABOARD_ROOT`:

```bash
FIESTABOARD_ROOT=/path/to/FiestaBoard pytest
```
