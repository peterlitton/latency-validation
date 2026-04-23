## Session 2.3 (ops) — Render infrastructure upgrade

**Date:** 2026-04-23
**Phase:** 2 complete → Phase 3 prerequisite
**Operator:** Peter Litton
**Scope:** Operational only, no code changes, no commits.

**Worked on.**
- Upgraded Render Background Worker instance type: Starter ($7/mo, 512 MB RAM, 0.5 CPU) → Standard ($25/mo, 2 GB RAM, 1 CPU).
- Upgraded Render persistent disk: 1 GB → 10 GB ($0.25/mo → $2.50/mo).
- Service redeployed cleanly on commit `7fcd208` (session 2.2 Phase 2 close) at 2026-04-23 13:07 UTC.

**Decided.**
- Standard tier selected over Pro ($85/mo). Workload is I/O-bound (three WebSocket connections writing JSONL), not CPU-bound. 2 GB RAM resolves the observed OOM issue; 4 GB would be over-provisioning. Upgrade in place via Render dashboard if Standard proves insufficient during Phase 3.
- Disk at 10 GB gives comfortable headroom for the 14-day Phase 6 measurement window. Estimated capture volume post-commit-6 (gamma snapshots removed): ~150-300 MB/day across Sports WS market_data + trades + API-Tennis (Phase 3). 10 GB supports the full window with buffer. Disks can grow but cannot shrink; 10 GB is a reasonable lock-in.

**Surfaced.**
- Pre-upgrade Events log showed **six OOM failures** of the Starter instance between 2026-04-23 11:01 and 11:17 UTC during live Phase 2 capture. Each failure produced "Ran out of memory (used over 512MB) while running your code" with subsequent instance recovery. This confirms the Starter tier was actively insufficient for sustained capture, not just a theoretical concern from the diagnostic-alongside-capture scenario session 2.2 originally flagged. Some event data likely lost during each failure cycle despite quick recovery.
- Instance type upgrade was not just Phase 3 prep — it resolved an active production problem that had been recurring in the hours before the upgrade.
- Post-upgrade: zero instance failures. Service stable on Standard.

**Next.**
- Phase 3 remains gated on two conditions:
  1. API-Tennis Business trial signup — complete the signup flow and have credentials ready. **Do not activate the trial yet.** Activation starts the 14-day clock and should happen at Phase 3 trigger time, not before.
  2. Tennis calendar watch — Phase 3 trigger requires a dense tennis week starting within 48 hours. Grand Slam ideal, ATP 1000 acceptable, Challenger-only week unacceptable. Operator confirms activation timing.
- No session-critical work until Phase 3 triggers. Capture continues running in background on Standard.

**AC status (Phase 2).**
No change. Phase 2 closed at commit 8 (session 2.2). All ACs met. This entry is operational and does not affect Phase 2 AC status.

**AC status (Phase 3 prerequisites).**
- [x] Render instance sized for continuous capture. *Standard tier, 2 GB RAM, 1 CPU. Deployed 2026-04-23 13:07 UTC.*
- [x] Render disk sized for 14-day window. *10 GB, ~$2.50/mo. Upgraded 2026-04-23.*
- [ ] API-Tennis Business trial signup complete (credentials ready, not activated).
- [ ] Tennis calendar trigger condition met.

**Operational cost summary.**
Total latency-validation monthly cost: ~$27.50 (Standard instance $25 + 10 GB disk $2.50). Within study budget; no further infrastructure decisions needed for Phase 3-7.

**Session close note.** No code changes, no commits, no handoff-gate questions. Operational state recorded for the next session's orientation. Service runs in background banking data on stable infrastructure until Phase 3 trigger fires.
