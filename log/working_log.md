---

## Session 4.2 — 2026-04-24 (Phase 4/5/6 continuation, incident triage)

**Context.** Session 4.1 ended ~14:00 UTC 2026-04-24 with the Render service
in an active crash loop. Six instance-failure events in eight minutes
(13:49–13:57 UTC 2026-04-24), orchestrator restarting every 1–2 minutes,
capture collecting between failures but degraded. Session 4.2 opens on
production incident triage per handoff priority 1: diagnose before touching.

**Commit 14: incident root-cause analysis and close.**

Log-only commit.

**Diagnostic path (read-only, no Shell).**

1. Render Events tab, reviewed last 28 events. Six `Instance failed: lxj8c`
   between 13:49 and 13:57 UTC 2026-04-24. Failure reason on each: "Ran out of
   memory (used over 2GB) while running your code." Final "Service recovered"
   at 14:00 UTC. No further failures since. Loop self-resolved ~65 min before
   session 4.2 start.

2. Render Metrics tab, memory graph last 12 hours. Baseline flat at ~5–10% of
   2 GB (≈100–200 MB) from 22:54 UTC 2026-04-23 through 13:55 UTC 2026-04-24.
   Two discrete spikes during the incident window reaching ~50% and ~55%
   (≈1.0–1.1 GB). Post-incident: flat baseline resumed immediately. No
   gradual climb at any point in the 12-hour window.

3. Render Logs tab, 14:42–15:13 UTC 2026-04-24. Orchestrator not restarting.
   Discovery polling every 60s cleanly. Two new Polymarket-side discoveries
   during the window (Gauff/Jeanjean 14:45 UTC, Ofner/Etcheverry 15:01 UTC).
   Service behaving normally.

**Root cause: in-container analysis memory contention.**

The memory graph shape rules out gradual leak. Baseline is stable at a tiny
fraction of the 2 GB budget for 8+ hours before the incident and flat again
for 65+ minutes after. A slow leak would show a climb; a restart-iteration
pathology (e.g. `_unresolved` file re-read on boot) would show a spike on
every orchestrator restart. Neither pattern present. What is present: two
isolated spikes clustered in a 15-minute window, each reaching OOM threshold,
each followed by container kill and restart.

These spikes correspond to Phase 4 calibration attempts run via Render Shell
during session 4.1 (Ostapenko/Waltert, ~23.5k Polymarket records + 496
API-Tennis records loaded into `code/analysis/loaders.py`'s list-based
readers). Calibration process lived inside the same 2 GB container budget as
the capture service; the combined footprint exceeded the limit; OOM killed
the container; restart; the retry (or buffered re-exec) spiked memory a
second time; OOM again; final restart cleared residual state and baseline
returned.

**Capture service memory behavior: healthy.**

Baseline ~5–10% of 2 GB across 8+ hours with 6–7 active matches and 9
cross-feed overrides loaded. No evidence of buffer accumulation in
`api_tennis_ws.py`, `sports_ws.py`, or the orchestrator. Handoff's leading
hypothesis (memory accumulation in capture workers) is not supported by the
metrics evidence.

**`_unresolved/2026-04-24.jsonl` file size: not implicated.**

Handoff noted this file at 1.14 GB as of 13:30 UTC 2026-04-24 and flagged
possible pathological iteration on restart as a candidate root cause. Metrics
rule this out: if the file were being read into memory on orchestrator boot,
every restart during the 13:49–13:57 UTC window would have produced a spike
to match the file size. Only two spikes are present, and they precede
restarts rather than follow them. The file is large but is on disk, not
memory. Pruning not required.

**Bug #4 (reconnect-when-empty): remains cosmetic.**

Metrics show no restart-correlated memory activity. No evidence Bug #4
contributed. Reassessed; remains parked.

**Operational rule added.**

No analysis workloads run on the Render container. Phase 4 calibration and
any future Phase 5–7 analysis runs on the Mac dev environment against
`~/latency-validation/local_archive/`. The Render container is capture-only
from this point forward. Ostapenko/Waltert calibration is not re-attempted
in-container; it may be revisited on Mac after the Priority 2 loaders
streaming rewrite lands (Session 4.2 subsequent commit).

**Phase 4 AC: remains CLOSED on Abidjan smoke-test** (Session 4.1 commit 12).
Not re-opened by this incident. The calibration attempt that triggered the
OOM was supplemental quality-signal work, not AC-gating.

**Phase 6 measurement window: data integrity note.**

During 13:49–13:57 UTC on 2026-04-24, capture collected between container
restarts but with 1–2 minute gaps per restart cycle. Six total failures.
Phase 7 analysis should flag this ~8-minute window for any matches active
during it; records either side of each gap carry `arrived_at_ms` and are
usable, but event continuity is not guaranteed across the gaps. This is a
degraded-capture note, not a data-loss note.

**Standing risks update:**

- **Render service memory / crash loop: CLOSED.** Root cause identified
  (in-container calibration), incident self-resolved, capture baseline
  healthy, operational rule added to prevent recurrence.
- Render tier / disk: closed (unchanged from session 4.1).
- Archive pruning: closed (unchanged).
- Diagnostic streaming rewrite: deferred post-Phase-7 (unchanged).
- Bug #4: reassessed during this incident; remains cosmetic.
- Plan §4 / §6 language revision: queued (unchanged).
- `code` package import hack in notebooks: low-urgency (unchanged).

**Session 4.2 remaining agenda (not this commit):**

1. Add 8 new overrides for currently-live and upcoming matches (operator
   inventory: Sinner/Bonzi, Putintseva/Kostyuk, Vavassori/Martin-Tiffon,
   Jeanjean/Gauff, Klimovicova/Yuan, Pridankina/Ferro, Tirante/Paul,
   Norrie/Machac).
2. `code/analysis/loaders.py` streaming rewrite (Priority 2). Convert
   list-loading to generator-based iteration so Phase 4+ calibration scales
   past Abidjan's 5k records without container memory pressure. Validation
   against the 14/14 synthetic-archive assertions from commit 11.

**End of commit 14.**
