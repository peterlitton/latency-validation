# Working log

## 2026-04-25 — scaffolding (step 1, compressed with 3 + 4)

Built Phase 1A scaffolding. Repo layout per project plan: `src/`, `static/`, `templates/`, plus governance dirs (`plan/`, `log/`, `findings/`, `methods/`, `design/`).

**Wired in:**
- `requirements.txt` (FastAPI 0.115, uvicorn, websockets, httpx, pyyaml, jinja2). Polymarket SDK pinned but commented — Phase 1C only.
- `render.yaml` — Standard tier, auto-deploy from main, `API_TENNIS_KEY` set in dashboard.
- `src/state.py` — in-memory `Match` dataclass and `matches: dict[str, Match]`. `snapshot()` returns live-then-upcoming list.
- `src/api_tennis_worker.py` — stub. Seeded five demo matches mirroring the v11 mockup so the dashboard renders something out of the gate.
- `src/main.py` — FastAPI app with lifespan-managed worker task, `GET /`, `GET /api/matches`, `WS /ws/matches` pushing snapshots every 1s.
- `templates/dashboard.html` + `static/dashboard.{css,js}` — v11 mockup translated to a JS-rendered table fed by the WS. Flag rendering is placeholder grey rect.

**Decisions:**
- WS pushes full snapshots, not diffs.
- No locking on `state.matches` — single asyncio loop, single writer.
- No archive-to-disk in v1.

---

## 2026-04-25 — step 2: real worker ported

Read latency-validation source (`code/capture/api_tennis_ws.py`, `config.py`, `cross_feed.py`, `archive.py`, `probe_api_tennis.py`). Confirmed:
- WS URL: `wss://wss.api-tennis.com/live?APIkey=...&timezone=UTC`
- No subscribe protocol; server pushes
- Messages: JSON list of dicts, ~24 fields per item, ~0.18 msg/s overall, ~1 update per match per minute
- Connection params: `open_timeout=10`, `ping_interval=20`
- Backoff: 1s initial, 60s max, 2x factor (reused as constants in this worker)
- `event_live` is unreliable — must check `event_status` instead

Wrote `src/api_tennis_worker.py` to replace the stub. Differences from latency-validation's worker:
- Writes to in-memory `state.matches` keyed by string event_key, not JSONL on disk
- No `cross_feed` routing — Phase 1A doesn't need Polymarket joins yet (deferred to 1C)
- DEMO_MODE env var path retained for design-work use without an API key

**Defensive-extraction strategy.** For fields whose exact name latency-validation didn't document — per-set scores layout, current game points, server identity, round label, country code — the parser tries multiple candidates and falls back to None. A `_warn_once(field, item_keys)` helper logs the available keys on the first item that misses a guess.

**Decisions made independently:**
- DEMO_MODE is now explicit opt-in (`DEMO_MODE=1` env var), not implicit.
- Finished matches are dropped from `state.matches` rather than retained.
- Status is inferred from `event_status` only, not `event_live`.

---

## 2026-04-25 — step 2.1: reconcile against Development Plan + Design Notes

Operator pushed the PM-Dashboard repo with two new documents I hadn't seen during steps 1–2: `plan/Development_Plan.md` and `design/Design_Notes.md`. Reconciled Step 2 worker against them; found three correctness issues, fixed two, deferred one.

**Two real bugs, both fixed:**

1. **Country field name was wrong.** Step 2 worker guessed `event_first_player_country` and `_logo`. Design Notes §6 confirms it's `event_first_player_country_key` / `event_second_player_country_key`. Patched `_player()`.

2. **Liveness counter measured the wrong thing.** Design Notes §8 says counter resets on any upstream message arrival. Step 2 frontend was resetting on every backend-to-frontend WS frame (always 1s), so the counter showed perpetual "1s" regardless of API-Tennis health. Fix touched `state.py` (added `source_timestamps` dict), `api_tennis_worker.py` (stamp timestamp on every frame), `dashboard.js` (read upstream timestamp, color dot per §8 thresholds), `dashboard.html` (dot IDs), `dashboard.css` (yellow/red/unknown states).

**One scope-vs-template question, deferred to empirical resolution:** Development Plan §1A excludes serve indicator, market price, flags, and tournament metadata beyond player disambiguation. My Step 2 dashboard renders all four. Decision: deploy as-is, decide empirically after the 10-minute test.

**Decisions made independently:**
- Snapshot payload contract changed from bare list to `{matches, source_timestamps}`. No backward-compatibility concern.
- The `polymarket` source slot is in `source_timestamps` from the start (always None until 1C).

---

## 2026-04-25 — step 2.2: pre-deploy hardening (resilience, empirical schema, instrumentation)

Three pre-deploy items to land before the 10-minute live-match test:

### 1. Reconnect-loop resilience (verification + one fix)

Reviewed `run()` and `_handle_message`. Five malformed-frame variants exercised against the live code: non-JSON, non-list-non-dict, dict-without-event-key, list-with-garbage-items-mixed-in, non-UTF8 bytes. All return cleanly with appropriate warnings. Per-item exception handling around `_apply_item` catches everything and logs.

One fix: minimum-time-between-attempts on clean close. Previously the supervisor reset backoff to 0 and reconnected immediately. If the server were in a state of accept-then-immediately-close, that's a tight loop. Added `await asyncio.sleep(WS_RECONNECT_INITIAL_SECONDS)` after clean close.

### 2. Empirical schema corrections (the bigger find)

Item 2 was supposed to be "tighten the status classifier from a guess to empirical truth." Looking at `latency-validation/code/analysis/normalize.py` to find observed status values, I found something more important: the analysis layer documents the **actual API-Tennis field shapes**, several of which I had guessed at in Step 2.

Three corrections landed from this empirical pass:

- **`event_game_result` is a string `"30 - 40"`, not a dict.** My parser was reading `item['event_game_result']` as a dict with `first`/`second` keys. Rewrote `_parse_current_game` to split the string. Defensive dict fallback retained for tier variants.
- **`event_serve` returns `"First Player"` / `"Second Player"`** (confirmed correct, parser simplified).
- **`event_final_result` is a string with full set tally** (e.g. `"6-4, 3-2"`), used by latency-validation's `ap_score`. This is the empirical source for set scores I was guessing at with `scores` list-of-dicts. Rewrote `_parse_set_scores` to try `event_final_result` first; falls back to the list-form parser if absent. Tiebreaks captured only from list-form (string format doesn't carry them).
- **Status classifier:** known live values start with `"Set "`; known finished set is `{Finished, Retired, Cancelled, Walkover}`. Anything else warn-once with the actual value and treat as upcoming. Pre-match status values aren't in the latency-validation corpus because that worker filtered them at discovery layer — first real run reveals what API-Tennis sends.

This is bigger than the original "tighten the classifier." The 10-minute test would have surfaced the game-result shape mismatch as schema warnings, but catching it now means the test starts with correct fields rather than hunting for them. Defensive fallbacks remain everywhere as belt-and-suspenders.

### 3. Schema-capture instrumentation

Added `_raw_sample_logged` global. First dict reaching `_apply_item` per process is logged in full at INFO level via `log.info("API-Tennis raw item sample (one-shot): %s", json.dumps(item, default=str))`. Subsequent items not logged. Guarantees one full-schema sample in Render logs without flooding.

### Smoke tests

- Empirical-shape synthetic item (matching latency-validation's normalize.py shapes): all eight extractions correct (tour, status, set_label, p1_sets, p2_sets, game, server, countries).
- Finished match: dropped from state.
- Unknown event_status (`Suspended`): warned once with the actual value, treated as upcoming.
- Defensive fallbacks: dict-shaped game-result and list-shaped scores both still parse correctly.
- DEMO_MODE: snapshot shape unchanged, timestamp cadence unchanged.
- One-shot raw-item log fired exactly once at INFO.

**Next:** operator pushes this tarball, sets `API_TENNIS_KEY` in Render env vars, watches deploy. The 10-minute test runs at the next live ATP/WTA/Challenger window. Two outcomes:
- Clean: working log entry by operator on whether dashboard felt useful, decision on 1B.
- Schema warnings: capture the warning lines plus the one-shot raw-item sample (now guaranteed in Render logs at INFO), bring back for one tight patch.
