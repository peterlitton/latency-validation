# Session 4.1 Intro — Phase 4 Calibration + Phase 5 Dashboard (Parallel)

**Project:** Latency & Validation Study (v1)
**Phase:** 4 (Calibration) and 5 (Minimal Dashboard), running in parallel with ongoing Phase 6 capture
**Previous session:** 3.1, closed 2026-04-23

---

## Orientation

Read these in order before substantive work:

1. `log/working_log.md` — ends with session 3.1 close. Phase 3 AC met empirically (three sources on one match).
2. `plan/Operator_Instructions_Parallel_Phase_4_5.md` — operator authorization to start Phase 4 and Phase 5 in parallel with Phase 6 data collection. Do not wait for more matches to accumulate.
3. `plan/Latency_Validation_Study_v1_1_Plan.md` — v1.2 current. Phase 4 and Phase 5 ACs unchanged.

## State at session open

- Render: Standard tier, 10 GB disk, failure notifications active
- API-Tennis Business trial: active through approximately 2026-05-07
- Capture running: three sources for in-play Madrid matches
- First smoke-test match captured end-to-end: `challenger-abidjan_constantin-bittoun-kouzmine_maxime-chazal_2026-04-23`
- Overrides file: first entry committed in session 3.1 — verify mechanism is functional before relying on ongoing curation
- Phase 3 close artifacts: commit 10, Phase 2-3 working log entries, plan at v1.2

## What this session does

**Phase 4 Calibration** — primary work of session 4.1:

- Normalize captured events for the smoke-test match across all three sources into common-schema view
- Manually reconcile game-boundary events across API-Tennis, Polymarket market_data, Polymarket trade
- Verify no silent drops
- Verify match identity resolution held across the match
- Verify capture host clock against external NTP reference (±10ms tolerance)
- Record preliminary jitter observations in working log

Phase 4 AC closes when evidence is sufficient for one match. Per operator instruction, do not wait for 3-5 matches. One match suffices for AC.

**Phase 5 Minimal Dashboard** — can start this session if capacity allows, otherwise next session:

- Plotly-based per-match timeline notebook
- Single time axis
- Continuous CLOB lines from market_data events (best bid, best ask, derived mid)
- Discrete event markers, one layer per source per event type, toggleable
- Crosshair and synchronized tooltips
- Build against the smoke-test match as reference

Phase 5 AC closes when the notebook renders a completed match with all three sources layered and toggleable.

## What this session does not do

- Does not build live-monitoring UI. Phase 5 is analysis-surface for completed matches, not live monitoring.
- Does not revise the plan document. §4 / §6 language cleanup is queued for a later session with other substantive work.
- Does not touch Phase 6 operational cadence. Data collection continues automatically.
- Does not re-litigate Phase 3 scope decisions. Three-source framing is settled.

## Standing disciplines in effect

- **Scope discipline (operator-issued in session 2.2):** Default to simplest option for problems that don't serve research questions or capture-layer correctness. Do not propose elaborate design options for low-value problems.
- **Empirical verification before code:** Read actual data before writing extractors, traversal logic, or analytical code. Session 2.2's "three unverified-schema-assumption bugs" pattern is the reason this exists.
- **Research-first for external APIs:** Session 2.1 / 2.2 / 3.1 established this. Continues.
- **Bundling authorized:** Mechanically-related deliverables can ship in one commit. Discovery moments still get full surface-and-pause treatment.

## Deliverables for session 4.1

1. Common-schema normalization code (or notebook function) that reads raw JSONL from all three sources and produces a single unified event stream
2. Reconciliation analysis for the smoke-test match — paste or summarize evidence
3. Clock verification — NTP check result
4. Working log entry capturing Phase 4 AC close (if met), preliminary jitter observations, and any surprises surfaced
5. If capacity allows: Phase 5 dashboard v1 notebook rendering the smoke-test match

## What to surface

- If reconciliation reveals structural misalignment across sources (timestamp drift, schema mismatch, event-type gaps), surface immediately. Trial clock is burning; fixing capture-layer bugs now is cheaper than Phase 7.
- If the overrides file mechanism is not actually working end-to-end for ongoing curation, surface it and propose a minimal fix. Operator needs this working for daily match pairing during Phase 6.
- If Phase 4 calibration requires more than one session, escalate to operator before continuing.

## Operator context

- Trial clock burning through ~May 7. Phase 4 and 5 in parallel is explicitly authorized.
- Daily check-in cadence ongoing. Operator will add overrides for new Madrid matches as they appear.
- Silent-capture-failure monitoring is via Render's built-in service failure notifications. Service-up is monitored; data-actually-flowing is not automatically monitored.
- PM-Tennis findings document (deferred) will be drafted after Phase 3 fully closes, not in this session.

## Session structure suggestion

Session-open self-check:

- [ ] Working log read, session 3.1 close note internalized
- [ ] Plan v1.2 read
- [ ] Operator parallel-work instruction read
- [ ] Smoke-test match's three JSONL files present on disk (verify via Render Shell)
- [ ] Overrides file present and readable (verify via Render Shell or GitHub)

If any fail, surface and pause before proceeding with Phase 4 work.

---

**Begin session 4.1.**
