# Team Scores Setup

![Team Scores on a Vestaboard Note](./board-display.png)

1. Install the plugin from its public GitHub HTTPS URL.
2. Open **Integrations** and enable **Team Scores**.
3. Select MLB, NFL, or both.
4. Choose favorite teams separately for each league.
5. Set the timezone used to display upcoming game times.
6. Keep the default refresh and relevance settings initially.
7. Choose **Team Scores for Note** as the trigger page.

The plugin refreshes every 10 minutes while idle, every 60 seconds during the final 30 minutes before a game, and every 30 seconds while a matching game is live. The idle and live intervals are configurable.

## Recommended Note Page

Create a three-line page using:

```text
{{team_scores.line1}}
{{team_scores.team_line}}
{{team_scores.line3}}
```

Center rows one and three and left-align row two. `team_line` adds one curated identity-color tile beside each team and automatically falls back to a compact plain score if unusually large scores do not fit.

To add restrained league accents around the centered first row, use `{{team_scores.accent_line1}}` instead of `{{team_scores.line1}}`.

## Optional Context Page

The default page does not change when richer provider data is available. To build a companion page, use any optional variables directly or use the ready-made context line:

```text
{{team_scores.line2}}
{{team_scores.line3}}
{{team_scores.context_line}}
```

`context_line` selects context appropriate to the game state and limits it to 15 tiles. Pregame it can show a broadcaster or pitching matchup, live it favors the current situation, and after a final it favors series context or records. Missing optional data resolves to an empty string.

## When Games Appear

- Live matching games rank first.
- Recently completed games rank next and remain eligible for the configured number of hours.
- Upcoming matching games follow, ordered by start time.
- Older finals are removed automatically.
- If no favorite teams are selected for a league, all teams in that league are eligible.

MLB and NFL team settings are separate, so identical abbreviations cannot be confused across leagues.

## Collections and Alerts

To select the sports page during the 30 minutes before a game, add this rule to a variable-mode collection:

```text
AND(team_scores.state == "scheduled", team_scores.minutes_until_start >= 0, team_scores.minutes_until_start <= 30)
```

To keep the sports page selected throughout a live game, add:

```text
team_scores.state == "live"
```

Rules are for steady conditions. Use the plugin's start, score, and final alert settings for momentary events. Those triggers briefly replace the current page, then FiestaBoard resumes the active schedule or collection automatically. All three alert types are enabled by default and can be disabled independently.

## Troubleshooting

### No matching game appears

- Confirm the desired league is enabled.
- Confirm the team is selected, or leave that league's team list empty to include every game.
- Increase **Upcoming Game Window** if the next game is more than seven days away.
- Recent final scores disappear after **Keep Final Scores** expires. The default is 12 hours.

### Alerts do not appear

- Enable the corresponding score, final, or game-start alert setting.
- Select a trigger page in FiestaBoard for this plugin.
- The first successful fetch establishes a baseline and intentionally emits no alert.
- A transition from scheduled to live is treated as a game-start event before any score comparison occurs.

### One league is temporarily unavailable

MLB and NFL are fetched independently. A working provider can continue supplying games if the other provider fails; FiestaBoard logs the provider error for diagnosis.
