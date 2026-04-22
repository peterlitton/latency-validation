# Working log — Latency & Validation Study, v1

One entry per session. Five lines is fine: what was worked on, what was decided, problems surfaced, what's next, any AC status change.

Read at session start. Appended at session end.

Scope changes to the plan are recorded here with a revision note; the plan document itself is revised in place.

---

## Session 1 — Phase 1 kickoff

**Date:** [fill in on session]
**Phase:** 1 — Foundation
**Operator:** [fill in]

**Worked on.**
- Created repo `latency-validation` with directory skeleton (`code/`, `plan/`, `log/`, `findings/`, `archive/` gitignored).
- Committed plan document as `plan/Latency_Validation_Study_v1.1_Plan.md`.
- Created working log (this file) and findings skeleton.
- [Provisioned PaaS host — fill in once done]
- [Installed baseline deps — fill in once done]
- [Ran hello-world smoke test — fill in once done]

**Decided.**
- Repo name: `latency-validation`.
- Plan filename: `Latency_Validation_Study_v1.1_Plan.md` (kept document-revision number in filename; collision with deferred-version "v1.1" accepted for now, to be resolved if/when iPhone-study plan lands).
- PaaS: [Render / other — fill in].
- Python version: 3.12.
- Baseline deps: `websockets`, `httpx`, `orjson`, `pytest`. Any additions recorded here.

**Surfaced.**
- [Any problems / questions / items to flag — fill in]

**Next.**
- Phase 2 — Polymarket capture. Build Sports WS and CLOB WS workers. Polymarket capture runs continuously from Phase 2 through Phase 6.

**AC status (Phase 1).**
- [ ] Plan committed to repo.
- [ ] Working log and findings skeleton committed.
- [ ] Capture host reachable, Python runtime verified, persistent disk mounted, env var store accessible.
- [ ] Hello-world deploy smoke test passed.

---

## Session 2 — Phase 2 session 2.1 (discovery loop + Sports WS worker)

**Date:** 2026-04-22
**Phase:** 2 — Polymarket capture
**Operator:** Peter Litton

**Worked on.**
- Archive layout, per-match meta.json, discovery delta stream.
- Canonical match_id scheme: `{tournament_slug}_{player_a_slug}_{player_b_slug}_{event_date}` with players alphabetically sorted.
- Match identity resolver skeleton with YAML overrides (pyyaml optional, graceful fallback if missing).
- Gamma discovery loop: polls `gateway.polymarket.us/v2/sports/tennis/events` every 60s, writes raw snapshots, filters doubles, flags ambiguous cases.
- Sports WS worker: rewritten twice. First attempt hand-rolled Ed25519 handshake based on public docs. Second attempt switched to the official `polymarket-us==0.1.2` SDK after verifying against PM-Tennis's `sweeps.py`.
- Orchestrator with per-worker supervision, SIGTERM handling, graceful shutdown with grace window.
- Plan bumped v1.2 → v1.3 (§5.4 refinements; see below).

**Decided.**
- JSONL wrapper: `{match_id, source, arrived_at_ms, raw: ...}` plus routing fields on WS events (`event_name`, `match_id_resolved`, `slug`). Minimal wrapper, raw preservation at capture time.
- Overrides file format: YAML.
- Canonical match_id: readable slug (rejected opaque event_id and hash).
- Per-worker supervision: each worker wrapped in `supervise()` helper; CancelledError propagates, everything else restarts after 5s delay.
- CLOB auth: deferred to session 2.2 (empirical probe).
- SIGTERM: caught, cancels tasks, gives 5s grace window. JSONL writes are line-buffered so mid-line kill loses at most the current line.
- **Transport layer: use `polymarket-us==0.1.2` SDK, pinned.** Matches PM-Tennis's validated version. Hand-rolled Ed25519 dropped. See Surfaced below for rationale.
- **Plan §5.4 conceptual-reuse rule refined:** independence is at data/analysis layers, not transport. Using the same upstream SDK as PM-Tennis does not count as importing PM-Tennis code. What does preserve independence: our timestamping, resolver, archive schema, analysis notebooks — all reimplemented from reading PM-Tennis's source.
- **Plan §5.4 brief-correction:** v1 brief §4.2 was wrong that Polymarket's WSes are "public read, no auth." Both Markets WS and CLOB WS require Ed25519-signed handshake auth. Inline correction, not a separate revision cycle.

**Surfaced.**
- Session 2.1's first deploy hit DNS failure on the Markets WS URL — my best-guess `wss://ws-subscriptions.polymarket.us/v2/markets` doesn't exist. Real URL is `wss://api.polymarket.us/v1/ws/markets`, authenticated. Confirmed against Polymarket US docs and PM-Tennis's sweeps.py.
- Subscription type is a **string** constant (`"SUBSCRIPTION_TYPE_MARKET_DATA"`), not a numeric code. My initial guess of integer `1` would have been rejected. Caught by reading PM-Tennis's `sweeps.py` line 180 before committing.
- Discovery loop worked on first deploy — Gamma returned 88 raw events, 8 active singles matches, canonical match IDs resolved cleanly.
- Session 2.1 code dependencies changed mid-session: initially added `pynacl` for hand-rolled Ed25519; dropped it when switching to the SDK. Net deps added this session: `pyyaml` (overrides), `polymarket-us==0.1.2` (transport). `websockets` removed from top-level deps (transitive via SDK).
- Render Python runtime is 3.14.3, not 3.12 (plan expected 3.12, Phase 1 working log also noted). All wheels install cleanly on 3.14.

**Next.**
- Session 2.1 continuation: operator completes Polymarket US KYC (iOS app), generates Ed25519 API keys at polymarket.us/developer, sets `POLYMARKET_US_API_KEY_ID` and `POLYMARKET_US_API_SECRET_KEY` in Render Environment. Service restarts; Sports WS comes online.
- After keys land: verify end-to-end Sports WS capture against a live match; reconnect test; meet Phase 2 partial ACs for session 2.1.
- Session 2.2: CLOB WS worker via same SDK (SDK exposes `client.ws.markets()` only — CLOB endpoint investigation TBD; may share the same markets channel via SUBSCRIPTION_TYPE_MARKET_DATA covering order book, or may be a separate SDK method).

**AC status (Phase 2).**
- [x] Discovery loop runs 1+ hour, produces non-empty polls, writes meta.json.
- [ ] Sports WS worker runs 1+ hours against live data. *(blocked on API keys)*
- [ ] Raw JSONL written with `arrived_at_ms` and `match_id` for Sports WS events. *(blocked on API keys)*
- [ ] End-to-end live match on both Polymarket surfaces. *(blocked on session 2.2 + API keys)*
- [ ] Reconnect test on both WS. *(blocked on API keys)*
