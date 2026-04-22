# Phase 2 — session checklist

Concrete order of operations for Phase 2. ACs from §6 Phase 2 of the plan in brackets. Phase 2 is estimated at 2 sessions; possibly 3 if CLOB subscription semantics or reconnect behavior requires live probing.

## Entry conditions

- [x] Phase 1 ACs met (plan, log, findings committed; Render host up; smoke test passed).
- [ ] Render service unsuspended.
- [ ] `POLYMARKET_US_API_KEY_ID` and `POLYMARKET_US_API_SECRET_KEY` available (needed for CLOB WS auth; Sports/Gamma are unauthenticated). Keys stay out of repo and out of chat — set directly in Render Environment.

## Session 2.1 — Discovery loop + Sports WS worker

### Before the session

- [ ] Skim PM-Tennis's `src/capture/discovery.py` for reference on the Gamma poll pattern. Do not copy; reimplement. §5.4 conceptual-reuse rule.
- [ ] Skim Polymarket US docs for Markets WS if accessible (`docs.polymarket.us/api-reference/websocket/markets`). Note the 100-slug-per-subscription cap.

### During the session

1. **Archive directory structure.** Decide final layout under `/data/archive/`:
   - `gamma/{date}.jsonl` — raw Gamma poll snapshots
   - `matches/{match_id}/meta.json` — per-match metadata (immutable once written)
   - `matches/{match_id}/discovery_delta.jsonl` — added/removed event IDs per poll
   - `polymarket_sports/{match_id}/{date}.jsonl` — raw Sports WS events
   - `polymarket_clob/{match_id}/{date}.jsonl` — raw CLOB WS events (built next session)
   - `api_tennis/{match_id}/{date}.jsonl` — raw API-Tennis events (Phase 3)

2. **Discovery loop.** Async httpx client, polls `https://gateway.polymarket.us/v2/sports/tennis/events` every 60s, paginates until a page returns fewer than the page limit. Writes raw snapshots, emits deltas, writes meta.json per newly-discovered match. Filters to singles; flags doubles/mixed. Verifies sport slug at startup against `/v2/sports`.

3. **Canonical match_id scheme.** Decide format (default: `{tournament_slug}_{player_a_slug}_{player_b_slug}_{event_date}`). Record decision in working log.

4. **Match identity resolver skeleton.** Single module with:
   - `resolve_polymarket(event_id, meta)` — returns canonical `match_id`.
   - `resolve_api_tennis(event_key, payload)` — stub for Phase 3.
   - `load_overrides(path)` — reads YAML overrides file, starts empty.
   - Ambiguous matches return `None` and log a flag rather than guessing.

5. **Polymarket Sports WS worker.** Connects to the Markets WS, subscribes to slugs from the current discovery set (up to 100 per subscription; spawn additional subscriptions if more), writes raw payloads as JSONL with `arrived_at_ms` and `match_id`. Handles reconnect on disconnect with exponential backoff capped at 60s.

6. **Worker orchestrator.** A main entry point (`code/capture/main.py` or similar) that runs the discovery loop and Sports WS worker as concurrent asyncio tasks. Each task is supervised — if it crashes, log and restart after a short delay. Use graceful asyncio cancellation on SIGTERM so Render's restarts don't corrupt JSONL.

7. **Update Render start command.** Change from `python code/phase1_smoke.py` to `python -m code.capture.main` (or whatever the entry point becomes). Redeploy.

8. **Live-run verification.** Watch Render logs for at least an hour. Expect:
   - Gamma poll log lines every ~60s with event counts
   - Meta.json written for any discovered live or scheduled matches
   - Sports WS connected, event messages appearing in the JSONL files
   - No crash loop

9. **Reconnect test.** Force a disconnect (Render's "Manual Deploy" triggers a restart, or kill via Shell). Verify the Sports WS worker reconnects and resumes writing within 60s. Document whether the WS supports replay on reconnect (does it backfill missed events, or do you lose the disconnect window?).

### Session-close ACs (partial — full Phase 2 ACs met at end of session 2.2)

- [ ] Discovery loop runs 1+ hour; at least one non-empty poll; at least one meta.json written. **[AC: discovery loop]**
- [ ] Sports WS worker runs 1+ hour; raw JSONL written with `arrived_at_ms` and `match_id`. **[AC: Sports WS run]**
- [ ] Reconnect exercised on Sports WS; recovery time and replay behavior documented in working log. **[AC: reconnect, partial]**
- [ ] Working log appended with decisions (match_id scheme, archive layout, subscription batching approach).

## Session 2.2 — CLOB WS worker + full validation

### Before the session

- [ ] Live matches available (check tour calendar — at least one match in-progress or imminent during the session).
- [ ] Render service running from session 2.1.

### During the session

1. **Determine CLOB subscription unit.** Empirically: connect to the CLOB WS with a known-active market from the discovery set, try subscribing by `market_slug` and by `marketSides[].identifier`. Record which works and what the payload shape looks like. Document in working log. (PM-Tennis has an open question here per H-020 research; our Phase 2 pins it.)

2. **Polymarket CLOB WS worker.** Same shape as Sports WS worker: connect, subscribe, write raw JSONL with `arrived_at_ms` and `match_id`, handle reconnect. Order book deltas and trade events both captured as-is.

3. **Integrate into orchestrator.** Third concurrent task alongside discovery loop and Sports WS worker.

4. **End-to-end match capture.** Identify a live singles tennis match on Polymarket US. Verify:
   - Discovery surfaces it.
   - Meta.json is written.
   - Sports WS events for that match are appearing in its JSONL file.
   - CLOB WS events for its moneyline markets are appearing in their JSONL file.
   - All events reference the same canonical `match_id`.

5. **Reconnect test on CLOB WS.** Same as session 2.1 for Sports WS. Document behavior.

6. **Deploy final Phase 2 build.** Polymarket capture now runs continuously from this point through Phase 6 (per §5.2). Verify the service stays up without intervention — set expectation of daily operator check-ins per §6 Phase 6 operator-availability spec, but for now verify it at least runs unattended overnight.

### Session-close ACs (Phase 2 complete)

- [ ] All four Phase 2 ACs from §6 met.
- [ ] At least one live match captured end-to-end on both Polymarket surfaces.
- [ ] Reconnect tested on both WS; behavior documented.
- [ ] CLOB subscription-unit question closed; decision recorded in working log.
- [ ] Working log appended with close-out entry.
- [ ] Render service left running (not suspended) — discovery and WS workers continue through Phase 3+.

## Phase 3 handoff

Phase 3 is gated on two conditions (§6 Phase 3): Phase 2 ACs met AND dense tennis week starting within 48 hours. Do not activate API-Tennis trial the moment Phase 2 closes; wait for the calendar.

Pre-Phase 3 prep the operator can line up between Phase 2 close and Phase 3 start:
- Check ATP/WTA tour calendar for next dense week (Grand Slam ideal, ATP 1000 acceptable, Challenger-only not acceptable).
- Review API-Tennis signup / trial-activation mechanics.
- Ensure `API_TENNIS_KEY` will be available at activation time, staged in Render Environment at that moment, not before.

## Known risks specific to Phase 2

- **Rate limits on Gamma.** PM-Tennis has run at 60s cadence without issue. If we observe 429s, back off to 90s or 120s and note in working log.
- **Slug cap behavior.** If active tennis events exceed 100 simultaneously, need multiple Sports WS subscriptions. PM-Tennis is still stress-testing this; our session 2.1 probably won't hit the cap but design should tolerate it.
- **CLOB subscription ambiguity.** If neither `market_slug` nor `identifier` works cleanly, escalate — this is a plan-assumption challenge, not a session-scope problem.
- **Render quiet-restart.** Render's Background Workers restart on deploys without warning. Graceful SIGTERM handling in the orchestrator matters; JSONL writes should be line-buffered or flushed frequently so partial writes don't corrupt files.
