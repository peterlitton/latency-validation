# Operator Instructions — Phase 4 and Phase 5 in Parallel with Data Collection

**Date:** 2026-04-23
**Context:** Latency & Validation Study v1, post-Phase-3 close
**Status:** Operator-directed reordering. No plan revision required — Phase 4 and Phase 5 scope and acceptance criteria unchanged.
**Audience:** Latency-validation next session Claude, and any subsequent sessions until told otherwise.

---

## Situation

Phase 3 closed as of session 3.1. Three data sources are capturing Madrid matches simultaneously. API-Tennis trial clock is running (~14 days through approximately May 7). Data accumulates automatically in the archive as matches go live.

The plan lays out phases sequentially (1 → 2 → 3 → 4 → 5 → 6 → 7), but nothing in the plan mandates strict sequential execution. Phases 4 and 5 only require:

- Phase 4: one or more matches captured across all three sources (Phase 3's smoke-test match already satisfies this minimum)
- Phase 5: known data structure + one match in archive as build target (both satisfied as of Phase 3 close)

Sitting idle for 3-5 matches before starting Phase 4 is unnecessary. Data will catch up regardless.

## Instruction

**Proceed with Phase 4 and Phase 5 work in parallel with ongoing data collection.** Do not wait for the archive to accumulate 3-5 matches before starting Phase 4. Do not wait for Phase 4 AC close before starting Phase 5.

## Sequencing

The following work can start immediately in the next session:

**Phase 4 (Calibration).** Start with the Bittoun-Kouzmine vs Chazal match from Phase 3 smoke-test. Run normalization layer. Produce common-schema view. Manually reconcile game-boundary events across the three sources. Verify no silent drops. Verify match identity resolution. Verify capture host clock against NTP. Record preliminary jitter observations.

As additional matches land in the archive during Madrid, expand Phase 4 reconciliation to include them. Phase 4 AC close when the evidence is sufficient, not when a specific match count is hit. The plan's "at least one test match fully reconciled" AC is already achievable today.

**Phase 5 (Minimal Dashboard).** Can start in the same session as Phase 4 or the next session. Build the per-match timeline notebook using the Bittoun-Kouzmine vs Chazal match as the reference case. Plotly, single time axis, continuous CLOB lines from market_data events, discrete event markers per source/type, crosshair, synchronized tooltips.

Phase 5 AC close when the notebook renders any completed match in the archive with all three sources layered and toggleable. Does not require a specific match count or richer analytical features — those are Phase 7 work.

**Phase 6 (Measurement Window).** Running in the background continuously. No session-critical work. Operator adds overrides as new Madrid matches go live. Daily log check as sanity backstop.

**Phase 7 (Analysis and Close).** Happens after API-Tennis trial expires around May 7. Unchanged by this reordering.

## What stays unchanged

- Phase 4 AC scope: reconcile at least one test match across three sources, verify clock, produce common-schema normalization, record jitter observations
- Phase 5 AC scope: per-match timeline view in Plotly notebook, layers toggleable, crosshair functional, operator-usable for spotting anomalies
- Phase 6 daily operator check-in cadence per plan §6
- Phase 7 analysis scope and research-question coverage
- Scope-discipline standing instruction: default to simplest option for problems that don't serve research questions or capture-layer correctness
- All commit-and-log discipline from prior sessions

## What is explicitly authorized

- Starting Phase 4 before the archive has "enough" matches. One match suffices for AC.
- Starting Phase 5 before Phase 4 completes, if a session has capacity for both.
- Bundling Phase 4 evidence and Phase 5 dashboard scaffolding in a single session where mechanically related.
- Iterating Phase 5's dashboard against ongoing capture data — treating it as a live development surface rather than a post-hoc analysis tool.

## What to surface

- If Phase 4 calibration reveals a structural issue with captured data (timestamp misalignment, silent drops, schema drift), surface immediately. Trial clock is running; fixing capture bugs during the window is expensive but better than discovering them at Phase 7.
- If Phase 5 dashboard work reveals that the current data structure can't express what research questions need, surface immediately. Same reasoning.
- If data collection fails silently (Render notifications miss something, capture runs but events stop flowing), surface and escalate to operator.

## Rationale

Three data points that motivate the reordering:

1. Data structure is known and stable as of Phase 3 close. No need to wait for more data before designing tools that consume the data.
2. Trial clock is already running. Every idle day is burn.
3. Building analytical tools in parallel with capture surfaces issues sooner — a dashboard revealing that event timestamps don't align would catch a problem in day 2 that would otherwise surface in day 15 during Phase 7 analysis.

The trial window's value comes from active work happening during it, not from waiting for the capture window to complete.

## Checkpoints

- **After first Phase 4 session:** common-schema normalization exists, at least one match reconciled, clock verified. Phase 4 AC can close if evidence is sufficient.
- **After first Phase 5 session:** notebook renders the smoke-test match with all three layers and basic interactivity. Phase 5 AC can close.
- **Ongoing daily:** capture continues, operator adds overrides, log records anomalies surfaced.
- **Around May 4-5:** transition preparation for Phase 7. Trial clock near expiry. Final match captures coming in.
- **After May 7:** Phase 7 analysis and v1 close.

## Session-open reading

When the next session opens, read this document alongside the working log and plan. Acknowledge this reordering in the session-open orientation, then proceed with Phase 4 (and optionally Phase 5) work.

---

**End of operator instructions.**
