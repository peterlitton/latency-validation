# Phase 2 acceptance tests

Operational procedures for the two Phase 2 ACs that require manual
action against the live service: reconnect tests on both Sports WS and
CLOB WS, and end-to-end capture verification on a live in-play match.

These are the remaining capture-correctness checks before Phase 2 closes.

## Context

Phase 2 ACs (plan §6) include:
- Sports WS and CLOB WS reconnect automatically after transient failure,
  resuming capture without duplicating or losing archived records.
- End-to-end: a single live match has matched events captured to the
  archive from both Polymarket surfaces with `arrived_at_ms` timestamps
  and correct `match_id` routing.

The Sports WS and CLOB WS are the same underlying `MarketsWebSocket`
connection in the `polymarket-us` SDK — both reconnect behaviors are
exercised by a single test on that connection.

## Reconnect tests

Three scenarios, each tested independently from Render Shell or the
Render dashboard. Run while at least one live match is being captured
so the resume behavior has observable events to check against.

### Scenario A — Markets WS forced disconnect

**Goal:** confirm the Sports WS worker catches connection loss, backs
off, reconnects, and resumes capture on the current slug set without
duplicating previously-captured events.

**Procedure.**

1. Identify an active match from the logs. Note one of its moneyline
   slugs (from `meta.json[moneyline_market_slugs]`) and the current
   tail of its events JSONL:
   ```
   tail -1 /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl
   ```
   Record the `arrived_at_ms` of the last event.

2. Force the Markets WS to close without killing the worker. The
   SDK's websockets layer exposes the underlying connection; simplest
   reliable method is to restart the service from Render dashboard
   (Manual Deploy → Clear Build Cache & Deploy not required; just
   Restart). SIGTERM triggers orchestrator shutdown → full reconnect
   on restart. Not a true "transient" test but exercises the same
   code path at a cost of ~15 seconds of capture.

   For a cleaner transient test without restarting: in Render Shell,
   find the worker's outbound connection in `netstat -tn | grep :443`
   and kill the TCP socket with a tool like `ss -K`. Requires the
   `iproute2` utilities; may not be available in Render's container.
   If unavailable, the restart path is sufficient.

3. Watch `Render Logs` for, in order:
   - `Markets WS close event` or `Markets WS connection issue` warning
   - `Reconnecting in N.Ns…` (backoff log line)
   - `Opening N Markets WS connection(s) for M slug(s).`
   - `Subscribed batch 1/1 with M slugs (market_data=..., trades=...)`
   - Per-event log lines resuming

4. Check the events JSONL on disk:
   ```
   tail -5 /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl
   ```
   New events should have `arrived_at_ms` values after step 1's recorded
   value. No duplicates of the pre-disconnect event (duplicates would
   show as two records with identical `raw` content but different
   `arrived_at_ms`).

**Pass criteria.**
- Reconnect happens within `WS_RECONNECT_MAX_SECONDS` (60s by default).
- Events resume flowing to the correct match directory.
- No duplicated events in the JSONL (the SDK does not re-send buffered
  messages on reconnect; only new events arrive).
- Backoff counter resets after successful reconnect (visible as
  `Reconnecting in 1.0s` on any subsequent transient loss).

**Fail modes to watch for.**
- Reconnect succeeds but subscribes to a stale slug set — check the
  subscribed slug count in the log matches `current_slugs()` at that
  moment.
- Worker crashes instead of catching — supervisor will restart it after
  5s, visible as `[supervisor:sports_ws] worker crashed (...); restarting`.
  This is a bug if it happens, not expected behavior.
- Backoff grows unboundedly — indicates the exception catch is too
  narrow and a non-transient error is being treated as transient.

### Scenario B — discovery worker crash

**Goal:** confirm the supervisor restarts a crashed discovery worker
within `WORKER_RESTART_DELAY_SECONDS` (5s default) and that the worker
picks up where it left off.

**Procedure.**

This is harder to trigger externally because discovery is a pure-Python
polling loop with no external connection to kill. Two options:

1. **Observed opportunistic:** if the log ever shows
   `[supervisor:discovery] worker crashed`, check that it's followed by
   `restarting in 5.0s` and then a successful `Poll complete:` line
   within ~70 seconds. Pass.

2. **Induced:** deploy a one-line change that raises an exception in
   `DiscoveryLoop.run_once` on a specific condition (e.g., the 3rd
   poll), verify supervisor catches and restarts. Revert the change
   immediately after verification. Adds a deploy cycle; only do this
   if scenario 1 hasn't organically surfaced.

**Pass criteria.**
- Crash caught by supervisor, not propagated to orchestrator.
- Restart within 5s + one poll interval.
- No loss of `_active` state beyond what a normal restart loses (the
  set rebuilds from the next successful poll).

### Scenario C — SIGTERM graceful shutdown

**Goal:** confirm `SHUTDOWN_GRACE_SECONDS` gives workers enough time to
flush in-flight writes, and no records are corrupted by a mid-write
kill.

**Procedure.**

1. Note the last `arrived_at_ms` in a live match's JSONL.
2. Trigger a service restart from Render dashboard.
3. Watch logs for:
   - `Received SIGTERM; triggering graceful shutdown`
   - `[supervisor:*] cancelled; propagating`
   - `Capture orchestrator stopped.` within ~5s
4. After the new service comes up, check the JSONL's last record parses
   cleanly (no half-line):
   ```
   tail -1 /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl | python3 -c "import json, sys; json.loads(sys.stdin.read()); print('OK')"
   ```
   Expected: `OK`.

**Pass criteria.**
- All workers cancel cleanly within the grace window.
- Final JSONL record is complete and parseable.
- On restart, worker reconnects and resumes capture without duplicating.

## End-to-end verification on a live match

**Goal:** confirm that during a single live tennis match, the full
capture pipeline produces well-formed archive data suitable for Phase 7
analysis.

### When to run

When a tennis match is actually live (`live=True` at Gamma; observable
as non-zero `active=` in `capture.discovery — Poll complete:` log line).

Prefer an ATP/WTA main-draw match with heavy order flow — volume gives
more events to check against, and heavily-traded matches surface more
potential edge cases.

### Procedure

1. **Discovery detected the match.**

   Check logs for a `Discovered match {match_id} (status=resolved)` line
   near the match start time. Record the match_id.

2. **Match metadata written.**

   ```
   cat /data/archive/matches/{match_id}/meta.json
   ```

   Verify:
   - `match_id` matches directory name.
   - `tournament_name`, `player_a_name`, `player_b_name` populated.
   - `event_date` is YYYY-MM-DD; `start_date_iso` is an ISO-8601 string.
   - `moneyline_market_slugs` contains at least one slug.
   - `asset_identifiers` contains at least two IDs (one per side).
   - `resolution_status` is `resolved`.
   - No stale fields from the session 2.1 bug era.

3. **Sports WS subscribed to the match's slugs.**

   From the logs, find the most recent `Subscribed batch` line after the
   match's discovery. Confirm at least one of the batch's slugs matches
   one in the match's `moneyline_market_slugs`.

4. **Events arriving and routing correctly.**

   ```
   ls -la /data/archive/polymarket_sports/{match_id}/
   ```

   Should show a `{YYYY-MM-DD}.jsonl` file growing over the match
   duration. Size check:

   ```
   wc -l /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl
   ```

   Event count should increase over subsequent checks.

5. **Per-event correctness.**

   Pick a recent event:

   ```
   tail -5 /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl
   ```

   For each record, verify:
   - `arrived_at_ms` is a numeric millisecond timestamp.
   - `source` is `polymarket_sports`.
   - `event_name` is one of `market_data`, `market_data_lite`, `trade`,
     `heartbeat`, `error`, `close`. Over the match duration, both
     `market_data` and `trade` should appear.
   - `match_id` equals the directory's match_id.
   - `match_id_resolved` is `true`.
   - `slug` is non-null and matches a slug in the match's `meta.json`.
   - `raw` contains a `marketData`, `trade`, or similar payload with
     the expected subscription-type content.

6. **Both market_data and trade event types present.**

   ```
   grep -o '"event_name":"[^"]*"' /data/archive/polymarket_sports/{match_id}/{YYYY-MM-DD}.jsonl | sort | uniq -c
   ```

   Expected: non-zero counts for both `market_data` and `trade` (trade
   counts may be small for low-volume matches). Both are captured on
   the same connection per the session 2.2 `subscribe_trades` addition.

7. **No cross-match contamination.**

   All events in the match's directory should have `slug` values that
   appear in the match's `meta.json[moneyline_market_slugs]`. Any slug
   outside that set indicates the subscription-lifecycle artifact
   characterized in the bug #2 closeout — a few such events at match
   transitions are expected.

8. **No tripwire WARNINGs.**

   Search the logs for the session 2.2 tripwire:

   ```
   Live two-PLAYER event has empty tournamentName
   ```

   None should appear for this match.

9. **Tree consistency.**

   Running the diagnostic:

   ```
   python -m code.capture.diagnose_bug2 --archive-root /data/archive
   ```

   should show the match's directory with `routed > 0`, `unresolved = 0`
   (or a handful of post-end events if the match ended during the
   capture window), and no cross-match contamination.

10. **After match ends.**

    Wait ~2-3 minutes after match end for settlement events to finish.
    Then verify:
    - Events stopped arriving (tail no longer grows).
    - The match directory's final event count is sensible for the
      match's duration (tens to hundreds of events per hour for
      low-volume matches; thousands for heavily-traded matches).
    - Discovery has removed the match from the active set (next
      `Poll complete` line shows a lower `active=` count if this was
      the only ending match).

### Pass criteria

All 10 checks pass for at least one live match. A single well-formed
match is sufficient to close the end-to-end AC — volume across matches
accrues during the actual 14-day measurement window.

### Record in log

After the verification passes, append a session entry to
`log/working_log.md` recording:
- Match ID verified.
- Match duration in UTC.
- Event count (market_data + trades).
- Any anomalies observed.
- AC closeout line.
