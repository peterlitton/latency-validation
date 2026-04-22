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

**Surfaced (bugs for session 2.2 to fix).**

1. **event_date bug.** `resolver.py` pulls from `event.get("eventDate")`; Gamma gateway doesn't populate that field. Every match_id lands with `_unknown-date` suffix. PM-Tennis fixed this at H-016 by sourcing from `startDate[:10]`. One-line fix. Orphan-directory migration needed after fix.

2. **Slug-routing stability.** Session 2.1 live-run showed: 8 matches subscribed on Sports WS; 7 of 8 had exactly 1 event routed to their match directory, with subsequent events going to `_unresolved/` despite the slug being correctly extracted from the payload. Abidjan (the one heavily-trading match) routed all 10 events correctly. Empirical check ruled out Gamma state flips — event remained `active=True closed=False` across 63 consecutive polls. Cause is somewhere in discovery's `_match_slugs` dict population or the Sports WS worker's reverse lookup; hypothesis trail intentionally dropped at session close, session 2.2 opens fresh.

3. **Unknown-tournament match.** At least one active match resolved to `unknown-tournament_unknown-date` — resolver couldn't extract `eventState.tennisState.tournamentName`. Captured regardless. Investigate in 2.2.

4. **Startup race (cosmetic).** Sports WS worker starts before first discovery poll completes and idles for 30s before picking up the slug set. Not a bug; tighten if cheap.

**Other observations.**
- Session 2.1's first deploy hit DNS failure on a guessed Markets WS URL. Real URL is `wss://api.polymarket.us/v1/ws/markets`. Codebase now uses the SDK, which owns the URL.
- Subscription type is a string (`"SUBSCRIPTION_TYPE_MARKET_DATA"`), not a numeric code. Caught by reading PM-Tennis's `sweeps.py` before committing.
- Deps this session: `pyyaml` (overrides), `polymarket-us==0.1.2` (transport). `websockets` removed from top-level deps (transitive via SDK). `pynacl` added then dropped during the hand-rolled → SDK pivot.
- Render Python runtime is 3.14.3, not 3.12. All wheels install cleanly.
- Polymarket US API keys copied from `pm-tennis-api` Render service to `latency-validation`. Same keypair; potential per-account concurrent-connection cap is a latent risk but did not surface during 2.1.
- Capture banking overnight: discovery snapshots to `/data/archive/gamma/`, Sports WS events to `/data/archive/polymarket_sports/` and `/data/archive/polymarket_sports/_unresolved/` until bug #2 is fixed.

**Next (session 2.2 scope).**
1. Fix event_date bug (`startDate[:10]`).
2. Diagnose and fix slug-routing stability (bug #2 above). Don't carry prior hypotheses — start from the empirical symptom.
3. Plan directory migration: rename `_unknown-date` directories and relocate `_unresolved` events to their proper match directories once bug #2 is understood.
4. Investigate unknown-tournament match.
5. CLOB WS worker via same SDK. Endpoint TBD (may be another subscription type on `client.ws.markets()`, may be separate factory).
6. Tighten startup race if cheap.
7. End-to-end capture verification on a live in-play match.
8. Reconnect tests on both Sports WS and CLOB WS.
9. Close remaining Phase 2 ACs.

**AC status (Phase 2) at 2.1 close.**
- [x] Discovery loop runs 1+ hour, produces non-empty polls, writes meta.json. *(63 polls, 8 matches, stable. meta.json match_ids carry bug #1.)*
- [~] Sports WS worker runs 1+ hours against live data. *(Connected 17:39 UTC, still running at session close. Raw events flowing; bug #2 routes most to `_unresolved`.)*
- [~] Raw JSONL written with `arrived_at_ms` and `match_id`. *(Written; `match_id` resolution affected by bug #2.)*
- [ ] End-to-end live match on both Polymarket surfaces. *(Blocked: bugs #1, #2, and CLOB WS not built.)*
- [ ] Reconnect test on both WS. *(Deferred to 2.2.)*

**Session 2.1 close note.** Capture infrastructure is live and running. Discovery loop is solid. Sports WS transport works — connects, authenticates, subscribes, receives events, writes JSONL. Two real bugs surfaced that gate Phase 2 ACs: match_id is missing the date component, and 7 of 8 matches have a slug-routing stability issue that sends events to `_unresolved`. Both must be fixed in 2.2 before a live-match capture AC can be met. No data is lost — everything is preserved in `_unresolved` with full payload + slug, recoverable by post-hoc migration. Session 2.2 opens fresh; do not carry this session's hypothesis trail on bug #2.
