# Cross-feed overrides — operator workflow

The API-Tennis worker routes incoming events by `event_key` → `match_id`
via `/data/archive/cross_feed_overrides.yaml`. This document covers how
to add an entry when a new match appears on both feeds.

## Why this is manual

Per plan §5.4 (v1.2 revision), cross-feed match identity is kept manual
in Phase 3. The two feeds use different shapes:

- Polymarket: `"Aryna Sabalenka"`, tournament `"Madrid Open"`, no stable
  external ID for the match
- API-Tennis: `"A. Sabalenka"`, tournament `"Madrid"`, stable `event_key` int

Auto-matching on initials-dot-surname plus tournament-name-minus-"Open"
is tractable but not reliable enough to trust without review for the
$80 trial window. Operator curation is bounded (~60-90 Madrid matches
plus Challengers over 14 days) and keeps identity errors at zero.

Fuzzy matching with operator review stays on the roadmap as a session
3.2+ stretch.

## Workflow

1. **A new match appears in the Polymarket discovery logs.** Look for
   `Discovered match ...` in Render Logs. Copy the full match_id:
   ```
   madrid-open_jasmine-paolini_laura-siegemund_2026-04-23
   ```

2. **Find the corresponding API-Tennis event_key.** Easiest path: use
   the REST `get_livescore` endpoint. On Render Shell:

   ```bash
   python3 -c "
   import httpx, os, json
   r = httpx.get(
     'https://api.api-tennis.com/tennis/',
     params={'method': 'get_livescore', 'APIkey': os.environ['API_TENNIS_KEY']},
     timeout=15,
   )
   for e in r.json().get('result', []):
     if 'Paolini' in e.get('event_first_player','') or 'Paolini' in e.get('event_second_player',''):
       print(e['event_key'], e['tournament_name'], e['event_first_player'], 'vs', e['event_second_player'])
   "
   ```

   Substitute the player name. Returns the `event_key` integer.

3. **Add the line to `/data/archive/cross_feed_overrides.yaml`.** On
   Render Shell:

   ```bash
   echo "12121266: madrid-open_jasmine-paolini_laura-siegemund_2026-04-23" >> /data/archive/cross_feed_overrides.yaml
   ```

   Or edit via `nano` / `vi` if you prefer visual confirmation.

4. **Wait for the next reconnect cycle** (or trigger one via Manual
   Deploy → Restart Service). The worker re-reads overrides on
   connect. New events for that event_key flow to the correct
   match directory.

5. **Previously-arrived events for that event_key** sit in
   `api_tennis/_unresolved/{date}.jsonl` and are not retroactively moved.
   Phase 7 analysis resolves them by joining on `event_key` rather than
   trusting directory placement (same pattern as the Polymarket
   `_unresolved/` note from session 2.2 Phase 7 analysis plan).

## Checking your work

After adding an override and waiting ~30s for reconnect:

```bash
ls /data/archive/api_tennis/
```

New directories appear for newly-routed matches. Tail one to confirm
events are arriving with `match_id_resolved: true`:

```bash
tail -1 /data/archive/api_tennis/madrid-open_jasmine-paolini_laura-siegemund_2026-04-23/$(date -u +%Y-%m-%d).jsonl | python3 -m json.tool
```

Record should show `"match_id_resolved": true` and
`"match_id": "madrid-open_..."` matching what you added.

## Common problems

**YAML parse error in logs.** Check for tab characters, unquoted strings
containing colons, or stray indentation. The worker falls back to empty
overrides and logs the parse error; everything routes to `_unresolved`
until you fix it.

**Entry added but events still going to `_unresolved`.** The worker
re-reads on reconnect, not continuously. Check `WS_RECONNECT_INITIAL_SECONDS`
(default 1s) and `WS_RECONNECT_MAX_SECONDS` (default 60s). If the
connection is stable and not cycling, trigger a restart.

**Wrong `match_id` string.** Polymarket match_ids use slug format
(`madrid-open_first-last_first-last_YYYY-MM-DD`). Must exactly match
the directory name under `/data/archive/matches/`. Typos land events in
a new directory with the typo'd name, not an error.
