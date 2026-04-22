# latency-validation

Latency & Validation Study — v1.

A 14-day observation-only measurement of how a third-party tennis feed (API-Tennis) and Polymarket's public surfaces (Sports WS, CLOB WS) deliver live-match events, captured to a common archive and analyzed against four research questions.

Observation-only. No trades. Validation, not competition — a null result counts.

## Repo layout

- `plan/` — source of truth for what v1 is doing. Start with `Latency_Validation_Study_v1.1_Plan.md`.
- `log/working_log.md` — one entry per session. Read at session start, appended at session end.
- `findings/findings.md` — structured around Q1–Q4. Evidence accumulates as matches are captured; written substantively in Phase 7.
- `code/` — capture workers, normalization layer, match identity resolver, dashboard notebooks.
- `archive/` — JSONL event archive per source per match. Gitignored. Lives on the PaaS host during capture; synced locally for analysis.

## Where to start

New to the study: read `plan/Latency_Validation_Study_v1.1_Plan.md` (§1 and §2 first, then §6).

Starting a session: read the working log, then the relevant phase in the plan.

## Status

Phase 1 — Foundation.
