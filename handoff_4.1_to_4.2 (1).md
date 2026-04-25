# Session 4.1 → 4.2 Handoff

**Session ended:** 2026-04-24, late afternoon CDT, Friday.
**Ended why:** Render service entered crash loop mid-session. Operator chose to stop rather than debug while fatigued.

---

## URGENT — Read This First

**Render service is in a restart loop as of ~13:49 UTC (8:49 CDT) 2026-04-24.**

- 6 "Instance failed" events in 8 minutes on Render Events tab before session ended.
- Each failure is followed by container restart, capture service re-starts cleanly, then fails again 1-2 minutes later.
- Capture service IS still collecting data between failures. Phase 6 data integrity degraded, not zero.
- Operator instruction: **do not SSH, do not run calibrations, do not restart** at start of session 4.2. Diagnose first.

**First action in session 4.2:**
1. Check Render dashboard Metrics tab. Memory graph over last 12-24 hours.
2. Check Events tab. Is the crash loop still active? How many instance failures since handoff?
3. Check Logs tab (last 30 min). Is `capture.orchestrator — Capture orchestrator starting` repeating every 1-2 minutes?

**Likely cause (unproven):** memory pressure. Service runs on 2 GB container. 9 active cross-feed overrides → more in-memory state than earlier in week. Plus operator ran Phase 4 calibration attempts in Render Shell during session 4.1, which loaded ~24k records into the same container's memory budget alongside the capture service. Suspected cascade: calibration pushed memory over threshold → OOM kill → restart → brief recovery → accumulation resumes → OOM kill again.

**Known good state:** before 13:49 UTC 2026-04-24, service was stable for weeks.

---

## Session 4.1 Accomplishments

Three commits shipped and live on GitHub/Render before crash loop began:

- **Commit 11** — `code/analysis/` module with loaders, normalize, reconcile, phase_4_calibration CLI. ~930 lines. 14/14 synthetic-archive assertions pass.
- **Commit 12** — Phase 4 AC close log entry. Evidence: Abidjan smoke-test match, NTP probe (+4.7ms mean vs ±10ms tolerance), 5219/5219 records carry expected match_id, 7.28 min cross-source overlap, one status transition reconciled (Set 2→Finished, +2.8s PM delay).
- **Commit 13** — Session 4.1 definitive close. Disk bump to 50 GB recorded as resolved standing risk. Mac dev environment captured. Six early-added pairings noted as stronger validation material than Abidjan when matches end.

Plus unnumbered bundles:
- `pair_overrides.py` — operator curation utility (session 3.1).
- `pair_overrides_batch2.py` — session 4.1 batch pairing, TARGETS hardcoded per-batch.

**Phase 4 AC: CLOSED (on Abidjan smoke-test).** Not re-opened by crash loop.

**Mac dev environment: LIVE.** Homebrew, Python 3.12, Git, venv, Jupyter + plotly/pandas/pyyaml/httpx, SSH key registered with Render, local_archive rsync (3.29 GB pulled), `refresh-archive` alias, analysis module imports confirmed via JupyterLab smoke-test cell.

---

## Late-Session Deliverables (after live work stopped)

After ending the session for live work, the operator requested two end-of-session documents that were generated and presented as files:

- **Memo to downstream analytics PM** confirming point-by-point tennis data capture and storage locations. Saved as `memo_pointbypoint_data.docx`. Validates clean. PM-to-PM tone. Covers: what's captured (cumulative pointbypoint array per WS message; set/game/point hierarchy with break/set/match flags), where it lives (Render canonical paths and Mac mirror paths), how to verify (one-liner Python), and four caveats (PM-only data source, cumulative not delta, mid-match override gaps, schema notes).
- **Bidding data storage** explained inline in chat: `polymarket_sports/<match_id>/<YYYY-MM-DD>.jsonl` on both Render and Mac mirror, containing interleaved `market_data` (book snapshots, ~205ms cadence) and `trade` (executions, ~9.7s cadence) records distinguished by `event_name`. Operator did not request a memo for this; was just orientation. If session 4.2 needs to draft a comparable bidding-data memo for the same downstream PM, the structure can mirror the point-by-point memo.

---

## Overrides State

`/data/archive/cross_feed_overrides.yaml` — 9 lines (confirmed via `cat` at 13:40 UTC):

```
12121255: challenger-abidjan_constantin-bittoun-kouzmine_maxime-chazal_2026-04-23
12121508: madrid-open_jelena-ostapenko_simona-waltert_2026-04-24
12121612: madrid-open_sorana-cirstea_tyra-caterina-grant_2026-04-24
12121796: challenger-rome_andrea-guerrieri_filip-jianu_2026-04-24
12121611: oeiras-4_lucia-bronzetti_polina-kudermetova_2026-04-24
12121395: madrid-open_elena-rybakina_gabriela-ruse_2026-04-24
12121523: madrid-open_ben-shelton_dino-prizmic_2026-04-24
12121437: madrid-open_arthur-fils_ignacio-buse_2026-04-24
12121512: madrid-open_emiliana-arango_linda-noskova_2026-04-24
```

**Pending overrides (not added, matches not yet live on API-Tennis at session end):**
- Putintseva vs Kostyuk (Madrid) — discovered on Polymarket at 13:52 UTC per capture log, but API-Tennis didn't see it during session.
- Yuan vs Klimovicova — not discovered on either feed during session.

Re-running `python -m code.analysis.pair_overrides_batch2` on Render Shell will try to pair both once both feeds see them. **Only do this AFTER crash loop is fixed.** The batch2 module has Fils/Buse and Noskova/Arango still in its TARGETS list; will re-propose them; operator ignores since they're already in file.

---

## The Ostapenko/Waltert Calibration Attempt (partial / aborted)

Operator wanted richer Phase 4 evidence than Abidjan's 7.28 min overlap. Ostapenko/Waltert finished 6-2, 7-5 (Ostapenko won). Event_status `Finished` confirmed.

Calibration attempt: `python -m code.analysis.phase_4_calibration --match-id madrid-open_jelena-ostapenko_simona-waltert_2026-04-24 --date 2026-04-24`.

**Got as far as:** RAW RECORDS LOADED step (step 2 of 6). Numbers were encouraging:
- 23,581 polymarket records (vs Abidjan's 5,072)
- 496 api_tennis routed records (vs Abidjan's 96 + 51)

**Did not complete.** Sections 3-6 (spans, overlap, reconciliation, gaps, identity) never ran. No output persisted. Shell cycled, container restarted, aborted.

**Not required for AC** — Phase 4 already closed on Abidjan. Just operator-initiated supplemental quality signal work. Can be re-attempted from Mac after streaming loader refactor.

---

## Diagnostic Evidence from Session End

**Capture log (pasted from Render Logs tab):**
- 13:49:38 UTC: orchestrator start, loaded 9 overrides, API-Tennis WS connected.
- 13:50:09 UTC: orchestrator start (restart #1).
- 13:52:53 UTC: orchestrator start (restart #2).
- 13:52:10 UTC: discovery saw `madrid-open_marta-kostyuk_yulia-putintseva_2026-04-24` (new match).

**System state at ~13:57 UTC (from `uptime` on Render Shell before it cycled):**
- Up 28 days, load average: 19.54 / 16.68 / 15.38.
- Load 19+ on 1-CPU container = massive saturation. Container thrashing.
- Note: `up 28 days` is the host, not the container. Container itself cycling every 1-2 min.

**Render Events timeline (from dashboard):**
- 8:40 CDT — deploy `be07276` went live (commit 13's code push for pair_overrides_batch2).
- 8:49 CDT — first instance failure. 9 minutes after deploy.
- 8:49, 8:52, 8:54, 8:55, 8:57 CDT — five more instance failures.

---

## Session 4.2 Priority Agenda

### Priority 1: diagnose and fix the crash loop

**Read Render Metrics / Events / Logs first. Don't touch Shell yet.**

Diagnostic order:
1. Memory graph for last 12-24 hrs on Metrics tab. Is memory gradually climbing? Spiking? Steady?
2. How many instance failures since handoff? Is loop still active or did it self-resolve?
3. Recent log pattern: is orchestrator restarting every 1-2 min, or has it stabilized?

If still looping: candidate root causes to investigate, ranked by likelihood:
- **Memory accumulation in capture workers** — in-memory state growing across hours/days with no flushing. Inspect `api_tennis_ws.py` and `sports_ws.py` for buffers that aren't cleared.
- **The `_unresolved` files are pathological** — as of 13:30 UTC today, `api_tennis/_unresolved/2026-04-24.jsonl` was 1.14 GB. If something iterates this file each restart, it'd explain load spikes.
- **Calibration attempts during session contributed** — unlikely to be the ongoing cause if loop persists after session end, but may have triggered the initial tipping point.
- **Bug #4 (reconnect-when-empty) firing aggressively** — parked as cosmetic; may have become non-cosmetic under new load conditions.

If self-resolved: still investigate root cause. Don't assume it's fine just because it stopped. Recurrence likely.

### Priority 2: move analysis to Mac permanently

Operator instruction at session end: "Fix properly next session — probably move calibration to Mac permanently to eliminate memory contention."

Plan:
- Rewrite `code/analysis/loaders.py` to stream records lazily (generators, not list-loading). Current design loads entire JSONL files into lists — fine for Abidjan's 5k, broken for larger matches.
- Calibration and dashboard work from now on runs only against `~/latency-validation/local_archive/` on Mac, via JupyterLab. Render container does capture only.
- Daily workflow: `refresh-archive` on Mac → run analyses locally. Never load archive records into capture container's memory again.

This likely eliminates the crash loop cause #3 above (if calibration attempts were a trigger) and is good architecture regardless.

### Priority 3: Phase 5 dashboard

Deferred until Priority 1 resolved. Once streaming loaders exist and Mac workflow is the norm, build Phase 5 in JupyterLab. Reference match: Ostapenko/Waltert (larger and richer than Abidjan). Plotly per-match timeline, single time axis, continuous CLOB lines from market_data, discrete event markers toggleable, crosshair, synchronized tooltips.

### Priority 4: operator curation continues

- Still need Putintseva/Kostyuk and Yuan/Klimovicova added to overrides if/when they go live on both feeds.
- Re-run `pair_overrides_batch2.py` on Render Shell after crash loop resolved.
- Long-term improvement: move pairing utility to accept targets via CLI args or YAML file rather than hardcoded list. Low-urgency.

---

## Standing Risks

- **Render service memory / crash loop: OPEN, URGENT.** Session 4.2 priority #1. Root cause unknown.
- Render tier / disk: closed (Standard tier, 50 GB, failure notifications on).
- Archive pruning: closed by disk upgrade.
- Diagnostic streaming rewrite: deferred post-Phase-7.
- Bug #4 (reconnect-when-empty): parked as cosmetic, but may be relevant to crash loop — reassess.
- Plan §4 / §6 language revision: queued, cosmetic.
- `code` package import hack in notebooks: low-urgency cleanup. Notebook preamble documented.

---

## Standing Instructions (carried from session 4.1)

1. Default to simplest option for problems that don't serve research questions or capture-layer correctness. No elaborate option trees for low-value problems.
2. Read relevant module BEFORE drafting scripts. Empirical verification against real data first.
3. Bundling authorized for mechanically-related deliverables. Discovery moments still surface-and-pause.
4. Questions presented inline as prose, not interactive widgets.
5. State plainly what options serve before proposing tradeoffs.
6. **Multi-line heredoc paste to Render Shell unreliable (4x failures now).** Default to repo modules for ad-hoc scripts. Shell has also shown output buffering/scrollout issues during this session — redirect to files when outputs are long.

## Operational Lesson Added This Session

**Do not run memory-heavy analyses on the Render container.** Capture service and analysis compete for the same 2 GB budget. Moving analysis to Mac permanently (Priority 2 above) is the fix. Until then, analysis runs are blocked.

Mid-match override addition still loses prior API-Tennis history. Overrides should be added at or before match discovery time.

---

## Context for Claude at Start of Session 4.2

Read this file first. Then consult the full transcript archive at `/mnt/transcripts/` if any detail above needs expansion.

Project is the Latency & Validation Study. Operator is Peter Litton. 14-day observation-only measurement study, API-Tennis WS vs Polymarket Sports/Markets WS. Research questions Q1 agreement / Q2 lag / Q3 CLOB reaction / Q4 reliability. Repo: https://github.com/peterlitton/latency-validation. Deploy via GitHub→Render auto-deploy.

Session 4.2 starts with a production incident to triage. Phase 4 is closed. Phase 5 is next when fixes are in. Phase 6 measurement window is running (degraded during the crash loop). Phase 7 analysis expected after API-Tennis trial expires ~2026-05-07.
