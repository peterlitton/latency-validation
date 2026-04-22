# Latency & Validation Study — v1 Plan

**Document version:** v1.1
**Document status:** Source of truth for v1. Revised in place if scope changes; revision note in working log.
**Audience:** Project manager and senior developer. Assumes fluency with REST/WebSocket APIs, JSONL, Plotly, and PaaS deployment.
**Scope commitment:** v1 only. Follow-on versions (v1.1–v1.8) are named and sized, not planned.

**Revision history.**
- v1.0 — Initial plan.
- v1.1 — Reconciled session budget (§6 intro, new §6.0 calendar map). Added clock-skew AC to Phase 4. Added operator-availability spec to Phase 6. Tightened Phase 2 reconnect AC. Clarified conceptual-reuse rule (§5.4). Pulled "Polymarket capture runs in background" into §5.2 and Phase 3. Flagged Q3 noise-floor as Phase 7 decision. Added archive-preservation and iPhone-recording-location to done criteria and §10.

---

## 1. Study in one paragraph

A 14-day measurement study comparing how a third-party tennis data feed (API-Tennis) and Polymarket's public surfaces (Sports WebSocket, CLOB WebSocket) deliver point- and game-level information for live ATP, WTA, and Challenger singles matches. The study captures each source's event stream to a common archive, then analyzes timestamps and event content to answer four research questions about agreement, lag, CLOB reaction time, and reliability. Framing is comparison and validation, not competition — a null result (sources agree, no material lag, fast CLOB reaction) is a valid outcome. Observation-only; no trades are placed.

## 2. Research questions

The four questions v1 must answer, each testable from the captured archive:

**Q1. Agreement.** Does API-Tennis agree with Polymarket's Sports WS at game and point boundaries within an acceptable delta? "Acceptable" is defined after Phase 4 calibration once empirical jitter is visible; the plan does not preset a threshold.

**Q2. Lag.** Does Polymarket's Sports WS lag API-Tennis materially? "Material" is framed relative to the delta a trading strategy would need to exploit it; the findings document reports the distribution, not a single number.

**Q3. CLOB reaction time.** Once a game boundary is known (per whichever source reports it first), how long does the CLOB take to re-price? Measured as time from the earliest game-boundary event to the first subsequent CLOB best-bid or best-ask change. Note: CLOB quotes move for reasons unrelated to game boundaries (routine requotes, unrelated trades). Whether Q3 applies a minimum price-move threshold, filters for causally-plausible reprices, or simply reports the raw distribution with a characterized noise floor is a Phase 7 analytical decision made against real data.

**Q4. Reliability.** How reliable is each source — drop rates, late events (events arriving out of order or after the next event), explicit errors, reconnect frequency?

## 3. Scope

**In scope (v1).**
- Live ATP, WTA, and Challenger singles matches on Polymarket US during a single 14-day measurement window.
- One third-party feed: API-Tennis WebSocket, Business tier trial.
- Polymarket Sports WS and Polymarket CLOB WS.
- Per-match metadata (player rank, tournament seed, server identity) preserved in archive for downstream versions.
- iPhone screen recordings captured opportunistically during the measurement window and archived for v1.1. Not annotated or analyzed in v1.

**Deferred, named, not planned.**

| Version | Scope | Rough size |
|---|---|---|
| v1.1 | iPhone app interface measurement (uses v1's screen recordings) | 3–4 sessions |
| v1.2 | Add SportsDataIO and Data Sports Group as additional feeds | 2–3 sessions |
| v1.3 | Tournament tier stratification analysis | 1–2 sessions |
| v1.4 | Sub-game CLOB squiggle analysis | 1–2 sessions |
| v1.7 | Official source calibration | 1 session |
| v1.8 | Pre-trial Polymarket baseline | 1–2 sessions |

Each version's go/no-go is decided after the prior closes. Likely realistic path: v1 + v1.1 plus 2–3 selected follow-ups.

**Deferred indefinitely.** Maker-cancel cadence and adverse-selection analysis (requires private-WS trade capture, which requires PM-Tennis activation). Suspended/retired/edge-case match analysis.

**Explicitly out of scope.** Trading of any kind. Use of PM-Tennis code, infrastructure, repo, or governance. Secrets in repo or chat.

## 4. Data sources

**API-Tennis.** Paid Business tier, $80/month, 14-day trial. WebSocket endpoint provides point- and game-level events. Activated in Phase 3; expires 14 days later. Single third-party source for v1.

**Polymarket Sports WebSocket** (`/v1/ws/markets`). Public read access. Game-level events. Already characterized by PM-Tennis; that documentation is reference only, no code or artifact dependency.

**Polymarket CLOB WebSocket.** Public read access. Order book deltas and trade events. Continuous price stream.

**Polymarket private WebSocket** (`/v1/ws/private`). Authenticated. Observation-only scope means no orders are placed, so this channel emits nothing. The plan documents the channel for v1.x reference but does not wire a capture worker for it.

**Match metadata.** Player rank, tournament seed, server identity captured per match from API-Tennis payloads. Preserved in archive. Multi-source metadata cross-checks deferred to v1.2.

## 5. Architecture

### 5.1 Capture host

Single managed PaaS instance. Render is the default; any equivalent (Railway, Fly.io) acceptable if Render is unsuitable at Phase 1. Python 3.12. Async workers. JSONL archive on persistent disk. NTP-synced (rely on the PaaS's default NTP; verify at Phase 4 calibration).

Separate service, separate repo from PM-Tennis. Same conceptual shape as PM-Tennis's `pm-tennis-api` but no shared code.

### 5.2 Capture workers

Three concurrent async workers:

1. **API-Tennis WS worker.** Subscribes to point and game events. Writes to `archive/api_tennis/{match_id}/{date}.jsonl`.
2. **Polymarket Sports WS worker.** Subscribes to game events for eligible matches. Writes to `archive/polymarket_sports/{match_id}/{date}.jsonl`.
3. **Polymarket CLOB WS worker.** Subscribes to order book deltas and trades for the markets associated with eligible matches. Writes to `archive/polymarket_clob/{match_id}/{date}.jsonl`.

Each worker's raw payload is written as-is, with an `arrived_at_ms` timestamp from the capture host and a resolved `match_id`. Raw preservation is non-negotiable — downstream analysis must be able to re-derive any field without replaying capture.

**Polymarket workers run continuously from Phase 2 onward**, including through Phase 3 trial activation and Phase 4 calibration. This banks Polymarket data before the trial clock starts and gives Phase 4 calibration a pre-existing corpus to reconcile against once API-Tennis comes online.

### 5.3 Normalization

A normalization layer reads raw JSONL and produces a common-schema view with fields:

```
(match_id, source, event_type, set_state, game_state, server, arrived_at_ms)
```

Normalization runs offline against the archive. It does not block capture. Specific field names beyond this schema are a Phase 2 decision.

### 5.4 Match identity resolution

Each source uses a different match identifier (API-Tennis `event_key`, Polymarket `asset_id`, any third identifier the CLOB exposes). A per-match mapping table joins them to a study-internal canonical `match_id`.

Built at match discovery by fuzzy name match (normalized player names, tournament, round) plus a manual overrides file. The overrides file starts empty and is appended to as edge cases surface. Format is a decision for Phase 2; a flat YAML or JSONL file keyed by canonical `match_id` with per-source ID fields is the default.

**Conceptual reuse rule.** Approach is reused from PM-Tennis: reading PM-Tennis source for reference is allowed; importing, vendoring, or copy-pasting code is not. Reimplementation from reading notes or memory is the bar. This applies to all PM-Tennis code throughout v1, not just the resolver.

### 5.5 Analysis environment

Local Mac. Jupyter notebooks. Plotly. Reads the JSONL archive over a synced copy or direct PaaS volume access (decision deferred to Phase 5; simplest is `rsync` at session start).

### 5.6 Credentials

Environment variables on the capture host: `API_TENNIS_KEY`, `POLYMARKET_US_API_KEY_ID`, `POLYMARKET_US_API_SECRET_KEY`. Never committed, never pasted in chat. No formal secrets manager — env vars are the rule.

## 6. Phase plan

**Session budget.** Seven phases, 7–10 working sessions total, spanning ~4–5 calendar weeks. Phase 6 spans 14 calendar days of capture but consumes only ~1 session-equivalent of operator time. The "5–7 sessions" figure from the brief was optimistic; the per-phase breakdown below reflects a more honest bottom-up estimate. Overrun against these per-phase estimates triggers a working-log note and a replan, not a governance ritual.

Each phase lists acceptance criteria. A phase is complete when its ACs are met and the working log entry is appended.

### 6.0 Calendar map

| Phase | Trigger | Work | Sessions | Calendar |
|---|---|---|---|---|
| 1 | Project start | Foundation | 1 | Week 1 |
| 2 | Phase 1 ACs met | Polymarket capture | 1–2 | Week 1–2 |
| 3 | Phase 2 ACs + dense tennis week within 48h | API-Tennis activation (starts 14-day clock) | 1 | Week 2 or 3 |
| 4 | Phase 3 ACs met | Calibration | 1 | Within trial week 1 |
| 5 | Phase 4 ACs met | Minimal dashboard | 1 | Within trial week 1 |
| 6 | Phase 5 ACs met | Measurement window | ~1 operator-equivalent | Trial weeks 1–2 (14 days) |
| 7 | Trial expiry | Analysis and close | 1–2 | Week after trial |

Phases 1–2 are flexible in calendar; the 14-day trial clock does not start until Phase 3. Phase 3's trigger condition (dense tennis week within 48 hours) means Phases 1–2 can finish days or weeks before Phase 3 activates.

### Phase 1 — Foundation

**Goal:** Repo exists, plan is written (this document), governance files exist, capture host is provisioned.

**Work.**
- Create repo (`latency-validation-study` or equivalent). Directory skeleton: `code/`, `plan/`, `log/`, `findings/`, `archive/` (gitignored).
- Write plan document (this one) to `plan/`.
- Create `working_log.md` with header and Phase 1 entry.
- Create `findings.md` with a skeleton structured around Q1–Q4.
- Provision Render (or equivalent) instance. Confirm Python 3.12, persistent disk, env var store.
- Install baseline deps (`websockets`, `httpx`, `orjson`, `pytest`).

**Acceptance criteria.**
- Plan committed to repo.
- Working log and findings skeleton committed.
- Capture host reachable, Python runtime verified, persistent disk mounted, env var store accessible.
- No code yet beyond a "hello world" deploy smoke test.

**Estimate:** 1 session.

### Phase 2 — Polymarket capture

**Goal:** Two Polymarket workers running against live data, writing raw JSONL, match identity skeleton in place. Runs continuously in background from this phase through Phase 6.

**Work.**
- Polymarket Sports WS worker. Subscribe, handle reconnect, write raw JSONL with `arrived_at_ms` and `match_id`.
- Polymarket CLOB WS worker. Same pattern. Subscribes to markets derived from currently-active Sports WS matches.
- JSONL archive directory structure and file-rotation policy.
- Match identity resolver, skeleton only: accepts source-native identifiers, returns canonical `match_id`, reads overrides file. Fuzzy name matching is a stub that flags ambiguous cases for manual override rather than guessing.
- Deploy to capture host. Run against live matches for at least one session's duration.

**Acceptance criteria.**
- Both workers run without crashing for 1+ hours against live data.
- Raw JSONL written, each event has `arrived_at_ms` and resolved or flagged `match_id`.
- At least one live match fully captured end-to-end on both Polymarket surfaces.
- Reconnect logic exercised at least once: kill connection, verify worker recovers within 60 seconds and resumes writing. Disconnect-window data loss is acceptable if the WS does not support replay; if replay is supported, backfill is required. Recovery behavior documented in working log (which WS supports what).

**Estimate:** 1–2 sessions. Flag: may spill if reconnect behavior on either WS is non-obvious.

### Phase 3 — API-Tennis activation

**Trigger condition:** Phase 2 ACs met AND tour calendar shows a dense tennis week starting within 48 hours. Grand Slam ideal, ATP 1000 acceptable, Challenger-only week unacceptable. Operator confirms activation timing.

**Goal:** API-Tennis trial activated, worker built and deployed, archive receiving events from all three workers. Polymarket workers continue running from Phase 2 throughout.

**Work.**
- Activate API-Tennis Business trial. Record activation timestamp — this starts the 14-day clock.
- API-Tennis WS worker. Same pattern as Polymarket workers: subscribe, handle reconnect, raw JSONL, `arrived_at_ms`, resolved `match_id`.
- Wire into match identity resolver. Populate initial overrides as name mismatches surface.
- Smoke-test against live matches.

**Acceptance criteria.**
- API-Tennis worker running on capture host alongside the two Polymarket workers.
- At least one live match captured on all three sources simultaneously.
- Match identity resolver handles all three sources; overrides file contains any manual mappings needed for the smoke-test matches.

**Estimate:** 1 session. Trial activation is the critical event; infrastructure must be verified before this phase starts.

### Phase 4 — Calibration

**Goal:** Confirm the captured data is analyzable before committing the measurement window to it.

**Work.**
- Select one or two test matches captured end-to-end across all three sources.
- Run normalization layer. Produce common-schema view.
- Manually reconcile a handful of game-boundary events across the three sources. Do timestamps sit within a plausible range? Do event types align? Is the server field populated consistently?
- Verify no silent drops: for a known sequence of games in a captured match, all three sources should show all games.
- Verify match identity resolution: no match has events incorrectly attributed across `match_id` boundaries.
- **Clock verification.** Query capture host's system clock against an external NTP reference (e.g., `pool.ntp.org`) and confirm offset is within ±10ms. Where source payloads include their own event timestamps, cross-check against `arrived_at_ms` for plausibility and record any systematic offset per source.
- Fix bugs that surface. Repeat until calibration matches pass.

**Acceptance criteria.**
- At least one test match fully reconciled across all three sources.
- No silent drops detected in the reconciled match.
- Normalization produces the common schema for all three sources.
- Capture host clock verified within ±10ms of external NTP reference. Any source-provided event timestamps cross-checked against `arrived_at_ms`; systematic offsets documented in working log.
- A preliminary sense of timestamp jitter is recorded in the working log — this informs the "acceptable delta" in Q1 when findings are written.

**Estimate:** 1 session. Flag: this is where trial-window burn is most likely. If calibration surfaces a blocker requiring >1 session to fix, escalate to operator before continuing — the trial clock is running.

### Phase 5 — Minimal dashboard

**Goal:** Live-monitoring dashboard sufficient to watch matches during the measurement window. Not the analysis surface.

**Work.**
- Per-match timeline view. Plotly. Single time axis.
- Continuous CLOB lines (best bid, best ask, derived mid).
- Discrete event markers, one layer per source per event type, toggleable.
- Crosshair and synchronized tooltips.
- Loads from a synced copy of the archive. Refresh is manual (re-run notebook cell) — live-streaming from capture host is not required at this phase.

**Acceptance criteria.**
- Given a completed match in the archive, the notebook renders its timeline with all three sources layered.
- Layers toggle independently. Crosshair shows timestamp, source, and payload at cursor position.
- One operator can use the dashboard to eyeball a captured match and notice obvious anomalies (missing segments, timestamp skew, layer mismatch).

**Estimate:** 1 session. Intentionally minimal. Full interactive surface is Phase 7.

### Phase 6 — Measurement window

**Goal:** 14 days of capture. Target 20–30 matches fully captured.

**Operator availability expectations.** The operator is not expected to live-monitor every match, but capture cannot be fully unattended either. Baseline cadence: one daily check-in (dashboard eyeball, worker status, overrides review, ~15 minutes) plus ad-hoc attention during major tournament sessions the operator happens to be watching anyway. A worker that dies silently between check-ins is a capture gap the study accepts — mitigated by, not eliminated by, the daily cadence.

**Alerting.** Out of scope for v1. No email-on-crash, no cron pings, no uptime monitor. If v1 experiences material gaps from unobserved worker deaths, lightweight alerting is a candidate addition for v1.2 or a mid-study hotfix — not a plan-time commitment.

**Work.**
- All three workers running continuously on capture host.
- Operator daily check-in: dashboard eyeball, worker status, overrides review.
- Operator responds to anomalies surfaced at check-in (missing match, worker crash, identity mismatch).
- iPhone screen recordings captured opportunistically for matches the operator is watching. Files saved unannotated to a designated folder (see §10).
- Working log appended after each session with match count, issues surfaced, any overrides added.
- No plan changes during the window unless capture is broken. The findings and follow-on work is Phase 7.

**Acceptance criteria.**
- Trial window used fully — capture runs for the entire 14 days from Phase 3 activation.
- 20+ matches captured end-to-end across all three sources. Captured matches span ATP, WTA, and Challenger (at least one of each if calendar permits).
- Archive is intact at window close — no corrupted JSONL, no unresolved `match_id` flags on captured matches (overrides file handles them).

**Estimate:** Spans 14 calendar days. Operator session time is ~1 session-equivalent across daily check-ins and overrides curation; the rest is unattended capture.

### Phase 7 — Analysis and close

**Goal:** Answer Q1–Q4. Write findings. Close v1.

**Work.**
- Trial expires. API-Tennis worker stopped. Polymarket workers may continue or stop at operator's discretion (archive for potential v1.8 use).
- Run analysis notebooks against the archive. For each of Q1–Q4, produce:
  - A headline number or distribution.
  - A chart.
  - A paragraph in the findings document explaining method and interpretation.
- For Q3 specifically, decide and document the noise-floor treatment: raw "first subsequent CLOB change" distribution, filtered by a minimum price-move threshold, or a causality filter. Whichever is chosen, findings note the alternatives considered.
- Iterate dashboard against real data: add aggregate views, richer toggles, anything Phase 5's minimal version surfaced as missing.
- Back up the archive off the capture host (local Mac copy and a cloud target — S3, Backblaze, or equivalent). Archive is the input to v1.2–v1.8; its durability post-v1 is a plan-level requirement.
- Review findings against v1 scope. Anything PM-Tennis v5 should know about goes into PM-Tennis's `pm_tennis_v5_ideas.md`, not this study's files.
- Write close-out working log entry. Tag v1 complete.
- Operator decides v1.x next steps.

**Acceptance criteria.**
- Findings document has a section per research question with evidence.
- Q3 noise-floor treatment chosen and documented.
- Dashboard renders per-match and at least one aggregate view.
- Archive backed up to at least one location off the capture host.
- Working log entry marks v1 closed.
- v1.x go/no-go decisions recorded in working log.

**Estimate:** 1–2 sessions. Flag: analysis depth is the variable — the plan commits to answering the four questions at a level sufficient for the findings document, not to exhaustive exploration.

## 7. Dashboard specification

Interactive Plotly-based, browser-rendered from a Jupyter notebook. Single time-axis per match.

- **Continuous variables as lines.** CLOB best bid, best ask, derived mid.
- **Discrete events as markers.** One layer per source per event type. Every layer independently toggleable.
- **Crosshair.** Vertical line follows cursor. Every layer's value at that x-position visible in tooltip.
- **Synchronized rollovers.** Hover any line or marker → exact timestamp, source, payload details.
- **Primary surface: per-match.** Aggregate views live in notebooks, added in Phase 7 as analysis surfaces need them.

Phase 5 ships the minimum viable version: per-match view, layers, crosshair. Phase 7 iterates — richer toggles, polished interactions, cross-match views — against the real captured archive when surprises have surfaced and analytical needs are clearer.

Specific layout, colors, and Plotly configuration are implementation decisions, not plan decisions.

## 8. Governance

Light. Three files, one ritual.

**`plan/Latency_Validation_Study_v1_Plan.md`.** This document. Source of truth for what v1 is doing. Revised in place when scope changes; revision note in working log.

**`log/working_log.md`.** One entry per session. Five lines is fine: what was worked on, what was decided, problems surfaced, what's next, any AC status change.

**`findings/findings.md`.** Structured around Q1–Q4. Evidence accumulates as matches are captured. Written substantively in Phase 7.

**Session ritual.** At session start, Claude reads the plan and working log. At session end, Claude appends to the working log. No other handoff artifact is required. No STATE.md, no decision journal, no RAID, no commitment file, no observation-active lock.

**PM-Tennis v5 ideas.** This study does not maintain its own v5 ideas file. Findings relevant to PM-Tennis v5 are added to PM-Tennis's `pm_tennis_v5_ideas.md`.

## 9. Risks

**Trial window burn.** Hardest risk. 14-day clock from API-Tennis activation. Phase 1–2 must complete before Phase 3 activation. Phase 4 calibration is the most likely place to lose days. Mitigation: Phase 2 ACs gate Phase 3, Phase 3's trigger condition includes the tour-calendar check, and Polymarket workers run from Phase 2 onward so calibration has real data to reconcile against the moment API-Tennis activates. If Phase 4 surfaces a blocker requiring >1 session, operator escalates before continuing.

**API-Tennis service fragility.** Provider's own site notes accidentally-deleted accounts. Single-source dependency for v1. Mitigation: archive lives on capture host, not with provider. Once captured, data is durable. v1.2 adds provider redundancy if fragility proves material.

**Match-identity resolution gaps.** Player names differ across sources; PM-Tennis needed several sessions to refine its overrides file, and v1 starts from scratch. Mitigation: resolver flags ambiguous cases rather than guessing. Overrides file is expected to grow during Phase 3–6; this is routine, not a blocker.

**Calendar dependency.** 14-day window is wasted if activated on an off-week. Mitigation: Phase 3's trigger condition requires a dense tennis week starting within 48 hours. Operator confirms before activation.

**Clock skew.** PaaS NTP is assumed correct. Verified at Phase 4 calibration against an external NTP reference with a ±10ms tolerance AC. If skew is material, it's caught there; findings note any residual uncertainty.

**Unobserved worker death during measurement.** No alerting in v1. A worker that dies between daily operator check-ins creates an unrecoverable capture gap. Mitigation: daily check-in cadence (§6 Phase 6). Escalation: if the first gap exceeds a session's worth of data, add lightweight alerting mid-study rather than wait for v1.2.

**Archive loss post-v1.** v1's archive is input to v1.2, v1.3, v1.4, v1.8. PaaS disk failure after v1 closes would silently kill follow-ons. Mitigation: Phase 7 AC requires backup to at least one off-host location.

## 10. Decisions deferred to implementation

The plan intentionally does not specify the following — they are Phase 1–2 implementation decisions, recorded in the working log when made:

- JSONL field names beyond the common schema.
- Overrides file format (YAML vs JSONL; default is YAML keyed by canonical `match_id`).
- Dashboard layout, color palette, Plotly configuration.
- Repo structure beyond the top-level directories named in §5.
- PaaS choice if Render is unsuitable.
- Archive sync mechanism for analysis (rsync, mounted volume, S3 sync).
- iPhone recording storage location during Phase 6 (capture host disk, operator's Mac, cloud target). Default: operator's Mac with a same-week cloud backup. Decide at Phase 5.
- Archive backup target and cadence for Phase 7 (S3, Backblaze, local RAID, etc.). Default: one local copy to operator's Mac and one cloud target; decide at Phase 7.
- Q3 noise-floor treatment (raw, price-move filtered, or causality filtered). Decide in Phase 7 analysis against real data.

## 11. Done criteria for v1

v1 is complete when:

1. All seven phases' ACs are met.
2. Findings document answers Q1–Q4 with evidence.
3. Archive backed up to at least one off-host location.
4. Working log contains a close-out entry.
5. Operator has made a go/no-go call on the next v1.x version.

---

**End of plan.**
