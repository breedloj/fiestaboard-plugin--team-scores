# Favorite Sports Setup

1. Install the plugin from its public GitHub HTTPS URL.
2. Open **Integrations** and enable **Favorite Sports**.
3. Select MLB, NFL, or both.
4. Choose favorite teams separately for each league.
5. Set the timezone used to display upcoming game times.
6. Keep the default refresh and relevance settings initially.

## Recommended Note Page

Create a three-line page using:

```text
{{favorite_sports.line1}}
{{favorite_sports.line2}}
{{favorite_sports.line3}}
```

Center all three rows. These fields are already limited to 15 tiles.

## When Games Appear

- Live matching games rank first.
- Upcoming matching games rank next, ordered by start time.
- Recently completed games remain eligible for the configured number of hours.
- Older finals are removed automatically.
- If no favorite teams are selected for a league, all teams in that league are eligible.

MLB and NFL team settings are separate, so identical abbreviations cannot be confused across leagues.
