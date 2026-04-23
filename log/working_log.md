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
- Plan bumped v1.1 → v1.2 (§5.4 refinements; see below). [Editorial correction committed session 2.2: session 2.1 originally recorded this as "v1.2 → v1.3"; the plan was v1.1 at session 2.1 start, so the correct bump is v1.1 → v1.2. Plan document updated accordingly at session 2.2 open.]

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

---

## Session 2 — Phase 2 session 2.2 (bug fixes, CLOB, end-to-end)

**Date:** 2026-04-22
**Phase:** 2 — Polymarket capture
**Operator:** Peter Litton

**Worked on (partial, landing commit 1).**
- Plan revision committed: v1.1 → v1.2. Four changes: document-version header, revision-history entry, §4 Polymarket WS auth correction (requires Ed25519 handshake; brief §4.2 was wrong), §5.4 conceptual-reuse refinement (independence at data/analysis layers, not transport). Session 2.1 decided these changes but didn't commit them; this session committed them on open.
- Bug #1 fix (event_date). `resolver.py` and `discovery.py` now source event date from `startDate` (with fallback to `eventDate`, then empty), via shared helper `resolver._extract_event_date`. `discovery._build_meta` uses the same helper so `meta.json["event_date"]` and the slug component stay consistent.
- Migration script `code/capture/migrate_unknown_dates.py`: one-shot, idempotent, dry-run-first. Walks `--archive-root`, finds `*_unknown-date` directories, reads `start_date_iso` from each meta.json, renames directory + rewrites match_id + event_date in meta.json, appends provenance note under `migrations`. Skips on: missing meta, missing/invalid `start_date_iso`, target already exists. Tested end-to-end on synthetic archive with all skip cases; re-run is idempotent.

**Decided.**
- Defensive fallback to `eventDate` retained in `_extract_event_date`: zero-cost insurance if Gamma schema ever populates it on a subset of events.
- Migration runs one-shot from Render Shell, post-deploy, not auto on service start. Preserves operator visibility into what was migrated.
- Scope discipline: this migration only touches `_unknown-date` directory names. `_unresolved/` event relocation is bug #2's migration, gated on diagnosis.

**Plan revision.** Plan bumped v1.1 → v1.2 (see first bullet above). Note: session 2.1 recorded this as "v1.2 → v1.3" but the plan was v1.1 at session 2.1 start; entry above has been editorially corrected with a parenthetical preserving the original claim.

**Next (within session 2.2, remaining scope).**
- Deploy commit 1; verify new matches get correct `_YYYY-MM-DD` suffix; run migration script; verify existing `_unknown-date` dirs are renamed.
- Bug #2 diagnosis (slug-routing stability). Fresh start from empirical symptom, no prior hypotheses.
- Bugs #3, #4 from session 2.1 intro.
- CLOB WS worker (same SDK, empirical auth probe).
- End-to-end live-match verification.
- Reconnect tests.
- Close remaining Phase 2 ACs.

---

**Commit 2 (scope refinements + player-extraction fix).**

**Context.** Post-deploy of commit 1, Render logs showed every discovered match had `players=''+''` and a corresponding match_id with a double-underscore gap between tournament and date (e.g. `challenger-abidjan__2026-04-22`). Desk-checked against PM-Tennis's `src/capture/discovery.py` (public repo, read-only reference). Found two things: (a) the US gateway's participant object is a typed wrapper (`{"type": "PARTICIPANT_TYPE_PLAYER", "player": {"name": ...}}`), not a flat `{"name": ...}`; session 2.1's top-level `p.get("name")` extraction silently returned empty names for every participant. (b) Gamma payloads include scheduled-future events across multiple calendar dates; the session 2.1 `active AND NOT closed` filter admitted pre-match events the study doesn't need.

**Scope refinements (operator-raised, not surfaced as bugs).**
1. **Nominees out of scope.** `PARTICIPANT_TYPE_NOMINEE` events are placeholder participants with no match being played and no third-party feed equivalent; nothing to compare across feeds. Discovery filter rejects them (0 PLAYER participants after typed extraction).
2. **Scheduled-future matches out of scope.** Study measures event timing during live play; pre-match events generate no comparable WS traffic. Discovery filter rejects on `live=False`. Strict stateless filter; 60s discovery cadence restores subscription on play resumption after delays. Sticky-active-set alternative rejected due to trapped-match failure mode.
3. **Handicap capture not in scope.** PM-Tennis captures pre-match ticks because its fair-price model needs a handicap; latency study has no fair-price model and no handicap concept. Recorded here to prevent future confusion.

**Worked on.**
- `resolver.py`: new helper `_extract_player_names` does typed dispatch on `participant["type"]`, extracts only `PARTICIPANT_TYPE_PLAYER` names from `participant["player"]["name"]`. Rewrote `resolve_polymarket_event` rejection order: ended/closed → not live → doubles (>2 PLAYER) → not singles (!=2 PLAYER). Added defensive WARNING tripwire for live two-PLAYER events with empty tournament name (bug #3 hypothesis check — fires if nominee filter doesn't fully resolve bug #3).
- `discovery.py`: imports and uses the shared `_extract_player_names` helper in `_build_meta` so `meta.json` player names agree with the canonical match_id.
- `_extract_event_date` kept, including the `eventDate` fallback (defense in depth, per scope call 3).
- 12 behaviour-test cases run against standalone harness of the extraction + rejection logic; all pass. Cases cover: clean resolve, ended/closed rejection (both orderings), scheduled rejection (explicit `live=False` and missing `live` key), nominee-only, doubles, PLAYER+NOMINEE mix, empty-tournament tripwire, clean-resolve no-warning, PLAYER with empty inner name, TEAM-type participants.

**Decided.**
- Port participant shape knowledge from PM-Tennis, rewrite the dispatch ourselves. Plan §5.4 reuse boundary — the participant type constants and shape are facts about Polymarket's API, not PM-Tennis IP; the dispatch logic is ours to write. Inline comment in `resolver._extract_player_names` names PM-Tennis as the shape source.
- Bug #3 (unknown-tournament) expected to resolve as a side effect of the nominee filter; tripwire WARNING confirms or refutes empirically. No separate fix needed.
- Bug #2 (slug-routing) simplifies indirectly: smaller `_match_slugs` dict, fewer subscriptions. Diagnosis still required but the surface area shrinks.
- Migration stays paused. Commit 2 deploys first; after a poll cycle confirms new match_ids have both tournament and player slugs populated correctly, then the migration can run against the (now correctly-populated) `_unknown-date` directories.

**Next.**
- Deploy commit 2. Watch logs for: (a) fewer discovered matches (live-only filter), (b) real player names in discovery log lines, (c) no tripwire WARNINGs firing. If tripwire fires, surface before proceeding.
- Run migration once dated `_unknown-date` directories have correctly-formed successors; see commit 1's Next.
- Bug #2 diagnosis from the now-smaller active set.
- Remaining scope unchanged: CLOB WS, end-to-end verification, reconnect tests, Phase 2 ACs.

---

**Post-deploy note (commit 2).** Indicator 1 showed `active=0` across the first two poll cycles post-deploy, `raw=94–95`. Matches the pre-deploy state on the same timeframe — no tennis live at 19:56–20:00 UTC, so the live-only filter had nothing to confirm or deny on resolved matches. Indicators 2/3/4 unread pending a live match. Bug #2 diagnosis and commit-1 migration dry-run proceed in parallel with the wait.

**Bug #4 (previously "startup race, cosmetic").** Promoted to a named bug as the live-only filter compounds it. Sports WS worker, on empty slug set, opens a Markets WS connection, receives no slugs to subscribe to, idles 30s, reconnects. Loop observed post-deploy. Wasteful but not data-losing. Tighten when convenient — conditions for fix: don't open the Markets WS connection if slug set is empty; re-check slug set at 30s intervals without reconnecting; only connect when non-empty.

**Tools shipped for session 2.2, commit 3.**

Commit 3 bundles two scripts and corresponding log entries. Triggered by the commit-1 migration dry-run surfacing a fundamental layout assumption error: v1 of the migration (and the original diagnostic draft) assumed meta.json sat alongside events in a single tree. The real archive has two parallel trees — `matches/{match_id}/meta.json` for metadata and `polymarket_sports/{match_id}/events-*.jsonl` for WS events. Both trees carry match_id-named directories; the session 2.1 bug #1 polluted both with `_unknown-date` suffixes.

- `code/capture/migrate_unknown_dates.py` **(v2 rewrite)**: two-phase migration. Phase 1 walks `matches/` using meta.json's `start_date_iso` as the authoritative date source. Phase 2 walks `polymarket_sports/`, resolving correct names either from phase 1's rename map (same-run) or via prefix scan of `matches/` for an already-renamed sibling (re-run). Skips cleanly on: target exists, missing meta, invalid date, no renamed sibling, multiple ambiguous siblings. Idempotent — re-runs are safe.
- `code/capture/diagnose_bug2.py`: offline diagnostic. Reads `polymarket_sports/` for routed-event counts per match and events in `_unresolved/`. Reads `matches/{*}/meta.json` (skipping `_unknown-date` dirs as superseded post-migration) for slug ownership. Reports: per-match event counts, unresolved-by-slug tally with owner attribution, orphan slugs (no meta.json owner), first-routed vs first-unresolved timing per match, tree-consistency check, cross-match contamination check. Read-only, re-runnable.

Commit-1 migration dry-run evidence (for the record):
- 8 `matches/*_unknown-date` directories, 6 of which have correctly-named siblings (commit 2 wrote fresh meta.json after matches went live post-deploy, resolving indicator 2 empirically — player names populated, match_ids correctly-formed). The remaining 2 (`challenger-rome`, `oeiras-4`) have no clean sibling yet.
- 8 `polymarket_sports/*_unknown-date` directories with no meta.json of their own (they never had one — meta.json lives in the other tree).
- v1 of the migration tried to walk both trees with the same logic, would have renamed 2 matches/ dirs without touching the 8 sports/ dirs, producing an internally inconsistent archive.
- v2 correctly plans: phase 1 renames 2 in matches/, skips 2 target-exists; phase 2 renames all 8 in polymarket_sports/ (6 via sibling lookup, 2 via rename_map). Tested end-to-end on synthetic archive mirroring the observed state; idempotent on re-run.

**Outstanding: two `matches/` _unknown-date dirs survive phase 1** for matches where commit 2 wrote a fresh correctly-named dir. Phase 1 skips them (target exists). Three handling options open for operator decision: leave as-is (provenance), delete (risk: any fields unique to old meta.json), or rename with a suffix like `.migrated` (preserves without polluting active namespace). Default in commit 3 is leave-as-is — diagnostic skips them for ownership purposes.

---

**Commit 4: glob fix.**

Single change. `code/capture/diagnose_bug2.py` glob updated from `events-*.jsonl` to `[0-9]*.jsonl` to match the actual filename pattern (`{YYYY-MM-DD}.jsonl` per archive.py). Nothing else.

Considered and rejected: a v3 migration to quarantine the orphan `_unknown-date` dirs. Drafted, tested, decided against. The orphan dirs hold session-2.1-era data that doesn't feed any of Q1–Q4 (no API-Tennis stream existed, the matches are over). Cleanup serves namespace hygiene, not research questions. Standing instruction now: default to simplest option for problems that don't serve research questions or capture-layer correctness. Migration stays where v2 left it; diagnostic will run against the dirty state. Orphan-dir noise is tolerable for diagnosing bug #2, which is about new event routing rather than historical placement.

**Bug #4 status.** Confirmed in commit 3's logs — Sports WS reconnect-when-empty loop visible at every 30s tick. Tightening still deferred; not blocking.

**Bug #2 status.** Diagnosis is the next thing. Commit 4 deploys diagnostic only. Run `python -m code.capture.diagnose_bug2 --archive-root /data/archive`, paste output. Bug #2 root cause from there.

**Next.**
- Deploy commit 4. Run diagnostic. Paste output for bug #2 analysis.
- Bug #2 fix in code.
- CLOB WS, end-to-end verification, reconnect tests, Phase 2 ACs.

---

**Bug #2: CLOSED — mechanism understood, not a problem for the study.**

Diagnostic ran against the real archive (~20k routed events, ~4.4k in _unresolved). Session 2.1's framing of the bug was wrong. Observed reality:

- 11 of 16 currently-known matches have zero events in `_unresolved`. Routing works fine for them.
- 4,387 of 4,391 `_unresolved` events are for slugs with NO currently-known owner in any meta.json. The single biggest (3,898 events, `aec-atp-ilisim-sookwo-2026-04-21`) is from a match dated 2026-04-21 — ended before session 2.2's first poll. Discovery dropped it from the active set; the Sports WS kept receiving post-end settlement events; reverse lookup (`match_id_for_slug`) failed because the slug had been removed from `_match_slugs`; events went to `_unresolved`.
- 4 events in `_unresolved` do have a currently-known owner: `aec-atp-andrub-vitkop-2026-04-23` → `madrid-open_2026-04-24`. This is the cross-day subscription-transition edge case, tiny signal.

Mechanism: the reverse slug→match_id lookup uses *current* state, not state-at-event-time. Matches that end mid-session produce a tail of post-end events (order-book settlement, clearing trades) that flow in faster than discovery removes the subscription, and those events fail the reverse lookup. Also produces the cross-match contamination seen in the diagnostic: 7 events (0.03% of total) in the wrong dir because slug ownership shifted between matches before the subscription updated.

Why this isn't a study problem: Q1–Q3 analyze live-phase events only. Post-end events aren't on the API-Tennis side (API-Tennis stops streaming at match end), so there's nothing to compare. Q4 (reliability) could in principle use "late-arriving post-end events" as a signal but the study's comparison scope is during-play, not after-end. The matches that matter — high-volume, live-phase, still active at archive time — route correctly.

No fix needed. Bug closed with empirical understanding recorded.

**Phase 7 analysis note.** Analysis notebooks must verify slug ownership by consulting each match's `meta.json[moneyline_market_slugs]`, not by trusting directory placement. The 0.03% cross-match contamination in session 2.2 is negligible but the pattern exists; an analyst seeing an unexpected slug in a match's events JSONL should read it as "subscription lifecycle artifact at match transition," not as data corruption.

**Next (Phase 2 closeout).**
- CLOB WS worker using `polymarket-us` SDK; empirical auth probe (session 2.1 deferral).
- Reconnect tests on Sports WS and CLOB WS.
- End-to-end verification on a live in-play match.
- Close Phase 2 ACs.
- Bug #4 (reconnect-when-empty loop) stays parked unless it interferes with operations.

---

**Commit 5: trades subscription + Phase 2 acceptance test procedures.**

**CLOB scope resolution (SDK probe, run in Render Shell).** The `polymarket-us==0.1.2` SDK exposes two WS factories, `markets` and `private`. `MarketsWebSocket.subscribe_market_data` (full order book), `subscribe_market_data_lite` (price-only), `subscribe_trades` (executions) — all three are subscription types on the same Markets WebSocket connection. Plan §4's distinction between "Sports WS" and "CLOB WS" doesn't map to a separate endpoint in this SDK; both are the same MarketsWebSocket. Session 2.1's existing Sports worker already captures CLOB order book state via `subscribe_market_data`. PM-Tennis has not yet built CLOB capture (per operator; their Phase 3 work, not yet landed) so no parallel implementation to read from.

**Change.** One commit, minimal. Added `ws.subscribe_trades(tr_request_id, batch)` after the existing `subscribe_market_data` call in `sports_ws.py:_run_once`. Handler for the `trade` event name was already registered from session 2.1 (`_on_trade` → `_handle_payload("trade", msg)`); no router change needed. Trade events flow to the same per-match JSONL as market_data events, distinguished by the `event_name` field on each record. Log line updated to show both `request_id` values per batch.

**Why the trades addition.** Research-question value for Q3 and Q4. Q3 (CLOB reaction time) gains execution-level signal — Phase 7 analysis can filter "noise requotes" from "requotes that moved an actual trade." Q4 (reliability) gains an independent stream-completeness channel separate from quote stream completeness. Cost is one line. Retrofitting later would mean re-subscribing on every existing connection or backfilling analysis with incomplete signal. Operator also noted: Phase 2 AC commits to "both workers"; even though the SDK collapses the distinction, honoring the two-stream capture commitment keeps the study faithful to its plan.

**Also shipped in commit 5:** `docs/phase_2_acceptance_tests.md` — procedures for the three remaining ACs (Markets WS reconnect test, discovery worker reconnect via code review, end-to-end verification on a live match). Operational documents, not code. Run manually from Render dashboard when conditions permit (reconnect test requires live match; end-to-end requires live match).

**Phase 2 AC closeout.**

| AC (per plan §6 / session 2.1 log) | Status | Evidence |
|---|---|---|
| Discovery loop runs 1+ hr, non-empty polls, meta.json written | **Met** | Session 2.1 ran 63 polls over ~1hr; session 2.2 accumulated thousands of poll cycles. Diagnostic confirmed 16 matches/*/meta.json files exist with correct schema post-commit-2. |
| Sports WS worker runs 1+ hrs against live data | **Met** | Sports worker running continuously since session 2.1 deploy 17:39 UTC 2026-04-22. Over 20,000 events routed across 16 matches by session 2.2 diagnostic time. |
| Raw JSONL written with `arrived_at_ms` and `match_id` | **Met (with caveat)** | All JSONL records carry both fields. Post-commit-2 records have `match_id_resolved: true` for live matches and correct `_YYYY-MM-DD` suffixes. Caveat: orphan `_unresolved/` events exist (post-match-end subscription-lifecycle artifacts, bug #2 mechanism understood and closed — not a capture-layer correctness failure). |
| End-to-end live match on both Polymarket surfaces | **Procedure-ready** | Procedure documented in `docs/phase_2_acceptance_tests.md` §C. Gated on live match availability — cannot run while tennis is not in play. Commit 5's trades subscription enables the "both surfaces" check. |
| Reconnect test on both WS | **Procedure-ready for Markets WS; discovery closed on code-review grounds** | Markets WS procedure in `docs/phase_2_acceptance_tests.md` §A (gated on live match). Discovery reconnect via `orchestrator.supervise()` code review in §B — catch-sleep-restart pattern confirmed. |

**Remaining operational work (not code, not blocking commit):**
- Run reconnect test (§A) when a live match is active.
- Run end-to-end verification (§C) when a live match is active.
- Append pass/fail notes to working log under the session they run in.

**Phase 2 substantively complete** pending those two operational runs. Moving to Phase 3 (API-Tennis activation) can proceed in parallel with those runs — they don't block Phase 3 work.

**Next.**
- Deploy commit 5. Confirm trades subscription starts producing `event_name=trade` records in match JSONLs when live tennis resumes.
- Operator: run §A and §C procedures on next live match window. Append results.
- Phase 3 kickoff: activate API-Tennis Business tier trial, build API-Tennis WS worker. Phase 3 triggers the 14-day measurement window clock.

---

**Commit 6: disk exhaustion, gamma/ snapshots removed.**

Post-commit-5 deploy landed during a live window with 6+ live matches. Service immediately started crashing on every poll: `OSError: [Errno 28] No space left on device`. `df -h /data` showed 974 MB disk at 100% used. `du -sh` breakdown:
- `gamma/`: 900 MB
- `polymarket_sports/`: 58 MB
- `matches/`: 268 KB

The `gamma/` directory was consuming 99% of disk. Discovery's `run_once` wrote every Gamma event from every poll to `gamma/{YYYY-MM-DD}.jsonl` — ~95 events × 60 polls/hour × ~8 KB/event = ~1 GB/day. Session 2.1 + session 2.2 continuous operation filled a day of free-tier disk.

**Research-question relevance check.** The `gamma/` snapshots don't feed Q1–Q4. Live-phase event data comes from `polymarket_sports/`. Discovery signal for Q4 (match add/remove transitions) is already captured in per-match `discovery_delta.jsonl` files under `matches/`. Raw Gamma polls were a "just in case" archive with no identified use.

**Action taken:**
1. Operator compressed `2026-04-22.jsonl` (the day with the best live-match coverage) to `.gz` and downloaded to Mac for optional future use. Source-of-truth data is on Mac; capture-host copy will be deleted.
2. Deleted `/data/archive/gamma/*` contents on Render Shell. Disk usage dropped from 100% to ~6%.
3. Code change: removed the `archive.append_jsonl(snap_path, ...)` write from `discovery.run_once`. Removed the now-unused `date_str` local. Comment block in place of the removed code documents why — future operator can reinstate temporarily for diagnostic purposes if ever needed.

**What was preserved.** Per-match `discovery_delta.jsonl` writes retained — those record added/removed match transitions in a fraction of the space (one line per change, not one line per event per poll), and they do serve Q4 reliability analysis.

**Plan touch.** None. Plan §10 lists "archive backup target and cadence" as a deferred implementation decision, not a preservation mandate. Plan §11 done-criterion #3 is "archive backed up to at least one off-host location" at end of v1 — refers to the final analysis archive, not raw polls. No plan revision needed; this is within the implementation-decision envelope.

**Data loss window.** Between commit-5 deploy (~13:42 UTC 2026-04-23) and disk-cleared restart, ~N minutes of Sports WS trade/market_data events for ~6 live matches were dropped at the `append_jsonl` call. Not recoverable. Q1–Q4 analysis has a 14-day window that hasn't started; impact is zero. Phase 2 AC verification runs get re-scheduled to next live window.

**Bug #4 reminder.** Sports WS reconnect-when-empty loop still parked. Unrelated to commit 6.

**Next.**
- Deploy commit 6. Verify discovery loop stops writing to `gamma/` (the directory should stay empty after restart even as polls run).
- Run Phase 2 acceptance tests (§A reconnect, §C end-to-end) on current live window — acceptance tests were blocked by the disk issue, now unblocked.
- Phase 3 kickoff unchanged.

---

**Commit 7: TEAM participants accepted.**

Commit 6 deployed, gamma writes stopped, disk clean. Acceptance-test step 1 (commit 2 four-indicator check) surfaced `active=0` across six polls. Initial read: live window passed. Operator pushed back — phone showed 5 live matches. Empirical probe against `gateway.polymarket.us/v2/sports/tennis/events` confirmed 7 events with `live=True`. Our resolver was rejecting all of them.

**Root cause.** `_extract_player_names` only accepted `PARTICIPANT_TYPE_PLAYER`. The active live events came back with `PARTICIPANT_TYPE_TEAM` — each participant wrapped with a `team` sub-object containing the player name at `team.name`. Session 2.2's `_extract_player_names` docstring explicitly said "teams don't appear in tennis singles — so they are deliberately not extracted here." That claim was empirically wrong. TEAM-typed participants do appear on singles matches on the US gateway.

The call to read PM-Tennis's `_extract_player_names` (which handles PLAYER, NOMINEE, and TEAM) and port only the PLAYER branch was the error. The commit 2 narrative said teams don't appear in tennis singles; should have been empirical — PM-Tennis handles TEAM for a reason.

**Fix.** `_extract_player_names` now accepts both PLAYER and TEAM via typed dispatch, reading `.name` from the corresponding nested sub-object. NOMINEE remains out of scope. Six-case standalone test confirms extraction is correct (TEAM pair, PLAYER pair, nominee-only rejected, mixed PLAYER+TEAM, incomplete team filtered, null inner dict filtered).

**Why this wasn't caught in session 2.1 or 2.2 earlier.** Session 2.1 routed 20k events correctly — those matches apparently returned PLAYER type. Today's live batch returned TEAM type. Gamma's schema choice is non-deterministic from our vantage point; a single event's `type` can apparently flip between PLAYER and TEAM across time or between matches. Session 2.2 captured 20k+ PLAYER events, accepted a PLAYER-only filter, and never saw a TEAM event during the deploy/verify cycle (all pre-commit-7 verification runs happened when Gamma was returning PLAYER — possibly because there were fewer live matches at those times and the PLAYER-typed matches happened to be active).

Pattern, third time: unverified schema assumption caused a silent-filter-out bug. Session 2.2 hit this for (1) eventDate field name, (2) top-level participant name vs nested, (3) now TEAM vs PLAYER wrapping. Lesson standing: schema probes against live Gamma responses should happen at session-open and after any live-data anomaly, not be backfilled from hypotheses.

**Phase 2 AC impact.** Acceptance-test runbook unchanged. Commit 7 deploys, discovery resumes finding live matches, then §A reconnect and §C end-to-end can proceed. No prior ACs regress.

**Next.**
- Deploy commit 7.
- Re-run acceptance-test step 1 (Poll complete with `active > 0`).
- Then steps 2-5 per the earlier sequence.

---

**Commit 8: Phase 2 close.**

All six Phase 2 ACs met. Full acceptance-test runbook executed against live data on 2026-04-23.

**AC closeout evidence.**

| AC (plan §6 / session 2.1 log) | Status | Evidence |
|---|---|---|
| Discovery loop runs 1+ hr, non-empty polls, meta.json written | Met | Continuous polls 14:43 UTC onward across session 2.2, 2+ hours of clean runtime. 33 meta.json files in archive, all with correct schema post-commit-7. |
| Sports WS worker runs 1+ hr live | Met | Active throughout post-commit-7 window; 20k+ events routed across 7+ concurrent matches this afternoon. |
| Raw JSONL with `arrived_at_ms` and `match_id` | Met | All records post-commit-2 carry both fields, `match_id_resolved: true` for live-phase events, strictly monotonic `arrived_at_ms` within each match. |
| End-to-end live match | Met | Aryna Sabalenka vs Peyton Stearns, Madrid Open Round of 64, 2026-04-23. Discovered 14:43:00 UTC, captured through match end (~14:57 UTC settlement phase). meta.json clean with full SportsDataIO provenance, WTA rankings, participant colour primaries. 1,900 events in match JSONL: 1,810 market_data + 90 trade. Single slug `aec-wta-arysab-peyste-2026-04-22` on all 1,900 records — zero cross-match contamination. Market state `MARKET_STATE_OPEN` with visible bids-side order book throughout; Sabalenka moved from 0.94 → 0.99 implied probability across the live window with $190K notional traded. Trade subscription verified flowing at ~5% of market_data volume (consistent with normal tennis moneyline flow). Zero WARNING lines anywhere in logs across 23+ minutes post-deploy. |
| Reconnect test | Met | Manual restart triggered 16:40:06 UTC. Clean SIGTERM → graceful shutdown sequence (both supervisors cancelled, orchestrator stopped) → 10s gap → service live → first poll `active=5 added=5 removed=0` (all 5 live matches rediscovered) → Sports WS resubscribe to 7 slugs with both `market_data=md-...` and `trades=tr-...` request IDs → Savannah Challenger resumed writing events at 16:41:17 UTC (204s gap from pre-restart 16:37:53 last event, service-down component ~10s, rest is poll-interval lag and resubscribe delay). Post-restart `arrived_at_ms` strictly > pre-restart, no duplicates, event_name preserved. |
| Discovery reconnect on crash | Met by code review | `orchestrator.supervise()` catches all non-CancelledError exceptions, logs, sleeps `WORKER_RESTART_DELAY_SECONDS` (5s default), and relaunches the worker coroutine via factory. Confirmed behaviour empirically during earlier commit-6 deploy cycle (not a research-question-critical test; code review sufficient). |

**§C step 9 (diagnostic) not run.** Diagnostic script loads all JSONL events into memory; during testing it triggered 7 consecutive OOM crashes of the capture service (Starter tier 512 MB cap). Skipped as non-essential for AC closeout since §C steps 2-8 all passed and the data-layer correctness is empirically verified. Diagnostic stays available for post-measurement forensic use; streaming rewrite deferred to post-Phase-7 per operator decision.

**Operational flags recorded for Phase 3.**

1. **Render tier upgrade: Phase 3 hard prerequisite.** Service ran out of memory 7 times during diagnostic testing. Starter tier's 512 MB cap is insufficient headroom for capture + any operational tooling. OOM during the 14-day measurement window would waste the $80 API-Tennis Business trial and invalidate data across multiple matches. Upgrade to Standard (or higher) before the Phase 3 trigger fires. Treat as a blocking prerequisite, not a nice-to-have.

2. **Diagnostic script: streaming rewrite deferred to post-Phase-7.** Problem doesn't exist during measurement (we don't run diagnostics during live capture). Current script is fine for between-phase forensic use when capture is off. Rewrite when Phase 7 analysis tooling gets its own sweep.

3. **Bug #4 (Sports WS reconnect-when-empty 30s loop): parked.** Cosmetic log noise, not data-losing. Tightening is trivial but doesn't serve a research question.

**Archive state at Phase 2 close.** `/data/archive/` uses 60 MB of 974 MB (6%). Three trees:
- `matches/`: 33 dirs, per-match meta.json + discovery_delta.jsonl (Q4 discovery-signal channel).
- `polymarket_sports/`: 33 dirs, per-match {YYYY-MM-DD}.jsonl event archives plus `_unresolved/` (post-match settlement artifacts, mechanism understood, analysis-safe per Phase 7 note).
- `gamma/`: empty, write removed in commit 6. Will stay empty.

Six `_unknown-date` orphan dirs remain from session-2.1-era captures (pre-commit-2 participant-shape bug). No cleanup performed per standing instruction — they don't serve research questions.

**Phase 3 unblocked pending tier upgrade.** Activate API-Tennis Business trial (triggers 14-day measurement clock), build API-Tennis WS worker, resume comparative capture.

**End of session 2.2.**

---

## Session 3.1 — 2026-04-23 (continues, Phase 3 kickoff)

**Context.** API-Tennis Business trial activated. 14-day measurement clock runs through ~May 7. Madrid Open in progress through May 3. Phase 3 scope per plan §6: API-Tennis WS worker, cross-feed match identity, smoke-test on a live match across all three data streams.

**Empirical schema probes before coding** (lesson from session 2.2's three schema-assumption bugs):

*Probe 1 (REST get_livescore, get_events, get_tournaments):*
- Event type keys: `265=Atp Singles`, `266=Wta Singles`, `281=Challenger Men Singles`, `272=Challenger Women Singles`.
- Madrid tournament keys: `2003` (WTA), `2004` (ATP). Tournament name on API-Tennis is just `"Madrid"` — not `"Madrid Open"` like Polymarket. Cross-feed tournament-name normalization needed (handled via manual overrides, not fuzzy matching, per operator Q2 decision).
- Player names are initials-dot-surname: `M. Trungelliti`, `D. Merida Aguilar`. Polymarket has full names. String-equality match across feeds is impossible.
- `event_live` is "1" (string) even for finished matches — it just means "inside the active livescore feed's window." Live-filter logic must check `event_status not in {"Finished", "Retired", "Cancelled"}`, not trust `event_live`. Mirrors Polymarket lesson.
- `pointbypoint` is full game history from match start, not deltas. Cadence implications for Q2 analysis (if we ever switch to point-level correlation).

*Probe 2 (API-Tennis WebSocket 60s capture):*
- Shape: every message is a JSON list. 11 messages over 60s, average ~8.5 items per message across ~11 unique matches live globally. Multi-match per message means an update to any match causes the whole active set to re-push.
- Update rate: ~0.18 msg/s overall, ~1 update per match per minute. Dramatically lower cadence than Polymarket (per-second on heavy matches). API-Tennis is the slower clock, Polymarket the faster.
- Madrid matches appeared in the stream (10 Madrid-tagged items).
- Item shape has 24 fields, matching docs.

*Probe 3 (Polymarket Markets WS event-type classification):*
- Probe 3 returned empty (picked a dead match), but the archive itself answered the question at higher statistical confidence: across every captured Polymarket event in every match archive this session (20k+ events, multi-hour capture on Sabalenka plus 30+ other matches), only two distinct `event_name` values exist: `market_data` and `trade`. Zero heartbeats, zero session-lifecycle events, zero game-state events.

**Scope finding — three sources reinterpreted.**

Plan §4 treats "Sports WS" and "CLOB WS" as distinct game-state-vs-orderbook streams. Session 2.2 established that the `polymarket-us` SDK collapses them into one MarketsWebSocket. Session 3.1 establishes that Polymarket emits no game-state events at all — only order book deltas (`market_data`) and trade executions (`trade`). Game state must be inferred from API-Tennis.

Three sources under empirical reality:
1. **API-Tennis WS** — game events (point/game/set/match transitions)
2. **Polymarket Markets WS `subscribe_market_data`** — CLOB order book state
3. **Polymarket Markets WS `subscribe_trades`** — CLOB trade executions

All three capturing to the same `match_id` directory is the Phase 3 AC target. Plan §4 language needs updating to reflect reality; deferred to plan-revision cycle (not blocking session 3.1).

**Commit 9: API-Tennis WS worker.**

Files:
- `code/capture/api_tennis_ws.py` — new. `ApiTennisWorker` class mirrors `SportsWorker` structure: connect → receive loop → route by event_key. Reconnect on transport errors with exponential backoff (reuses Polymarket's `WS_RECONNECT_*` constants). Idle-waits forever if `API_TENNIS_KEY` is unset rather than crash-looping.
- `code/capture/cross_feed.py` — new. Loads `cross_feed_overrides.yaml`, maps `event_key` (int) → `match_id` (str). Empty overrides file = everything routes to `_unresolved`. YAML parse errors log and fall back to empty, worker keeps running.
- `code/capture/config.py` — adds `API_TENNIS_KEY`, `API_TENNIS_WS_BASE`, `API_TENNIS_TIMEZONE` (UTC default), `CROSS_FEED_OVERRIDES_PATH`.
- `code/capture/main.py` — adds third supervised worker (`supervise("api_tennis_ws", ...)`). Orchestrator changes mechanical.
- `cross_feed_overrides.yaml` — new file, empty with comment header documenting format.
- `docs/cross_feed_overrides.md` — new. Operator workflow for adding entries as matches appear on both feeds.

`archive.py` already has `api_tennis_path` defined (Phase 2 preparation) — no edits needed there.

**Scope decisions (session 3.1, explicit):**

- Q1: **Raw preservation, no dedup.** Per plan §5.2. Each item of each message is archived individually with shared `arrived_at_ms` (captured at message receipt, not per-item). Phase 7 analysis decides dedup semantics against real data.
- Q2: **Manual overrides, no fuzzy matching.** Operator edits `cross_feed_overrides.yaml` as matches appear. Unresolved events land in `api_tennis/_unresolved/{date}.jsonl`, recoverable at analysis time via `event_key` join.

**Not yet done (post-deploy work):**

1. Deploy commit 9. Confirm `[supervisor:api_tennis_ws] starting worker` appears in logs and `API-Tennis WS connected. Streaming events.` follows without reconnect loops.
2. Confirm `/data/archive/api_tennis/_unresolved/2026-04-23.jsonl` grows (empty overrides = all events unresolved).
3. Pick one live match on both feeds (smoke-test candidates from operator: Budkov-Kjaer vs Opelka, Savannah Challenger). Add its `event_key → match_id` to overrides.yaml.
4. Watch for `/data/archive/api_tennis/{match_id}/{date}.jsonl` to appear within 60s (reconnect cycle).
5. Verify tail record has `match_id_resolved: true` and the expected match_id.

**Open for session 3.2+:**

- Plan revision to reflect three-source reality (§4 language, §6 AC).
- Post-match check procedures for API-Tennis source (mirror runbook §C steps 6-10 for api_tennis/ tree).
- Reconnect test for API-Tennis WS (mirror runbook §A).
- Phase 3 close-out AC table once smoke-test passes.

**Standing risks from session 2.2 still live:**
- Render tier upgrade before full Phase 3 measurement window. Still Starter tier unless you've upgraded since. Recommend confirming upgrade before committing the 14-day trial budget.
