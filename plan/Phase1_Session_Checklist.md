# Phase 1 — session checklist

Concrete order of operations for the Phase 1 session. ACs from §6 Phase 1 of the plan in brackets.

## Before the session

- [ ] PaaS account ready (Render default; alternative if Render unsuitable).
- [ ] Git host account ready (GitHub or equivalent).
- [ ] Tour calendar sanity-checked for rough Phase 3 timing (not a Phase 1 AC, but informs whether Phase 2 should start immediately after Phase 1 or wait).

## During the session

### 1. Repo

- [ ] Create empty repo `latency-validation` on git host.
- [ ] Clone locally.
- [ ] Drop in the Phase 1 artifacts from `/mnt/user-data/outputs/latency-validation/`:
  - `README.md`
  - `.gitignore`
  - `pyproject.toml`
  - `plan/Latency_Validation_Study_v1.1_Plan.md`
  - `log/working_log.md`
  - `findings/findings.md`
  - `code/phase1_smoke.py`
  - Empty `archive/` (gitignored; `.gitkeep` if needed to track the directory)
- [ ] Initial commit. **[AC: plan committed; log + findings skeleton committed]**

### 2. PaaS provisioning

- [ ] Create Render (or equivalent) service from the repo.
- [ ] Set runtime to Python 3.12.
- [ ] Attach persistent disk; mount path `/data` (or whatever the PaaS permits). Set `ARCHIVE_ROOT=/data/archive` env var.
- [ ] Confirm env var store is reachable. Leave `API_TENNIS_KEY`, `POLYMARKET_US_API_KEY_ID`, `POLYMARKET_US_API_SECRET_KEY` unset for now — Phase 1 doesn't need them, Phase 2/3 will.
- [ ] Set service start command to `python code/phase1_smoke.py`.
- [ ] Deploy. **[AC: capture host reachable; runtime + disk + env var store verified]**

### 3. Smoke test

- [ ] Deploy completes, logs show "Phase 1 smoke test passed."
- [ ] If anything fails, fix and redeploy until it passes. **[AC: hello-world deploy smoke test]**

### 4. Close

- [ ] Fill in dates, operator name, PaaS choice, and AC checkboxes in `log/working_log.md` Session 1 entry.
- [ ] Commit the updated working log.
- [ ] Phase 1 done when all four ACs are checked.

## Phase 2 handoff

Phase 2 starts when Phase 1 ACs are met. Phase 2's "start when" is "Phase 1 ACs met" — no calendar gate. Phase 3's trigger condition (dense tennis week within 48 hours) means Phases 1–2 can finish well before Phase 3 activates, so there's no rush from Phase 2 into Phase 3.

Key Phase 2 prep the operator can line up in parallel:
- Polymarket Sports WS endpoint + auth model reconfirmed (plan says `/v1/ws/markets`, public read).
- Polymarket CLOB WS endpoint + how to derive relevant markets from active Sports WS matches.
- Skim PM-Tennis's match-identity resolver *for concept only* (conceptual-reuse rule, §5.4 — reading allowed, importing not).
