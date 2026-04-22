"""Capture configuration — env-var-driven constants.

All tunables live here so workers don't sprinkle os.environ reads throughout
the codebase. Import what you need; mutate nothing.
"""

from __future__ import annotations

import os
from pathlib import Path


# --- Paths ------------------------------------------------------------------

# Root of the on-disk archive. Mounted as a Render persistent disk at /data.
# Phase 1 smoke test verified this exists and is writable.
ARCHIVE_ROOT: Path = Path(os.environ.get("ARCHIVE_ROOT", "/data/archive"))

# Overrides file for match identity resolver edge cases. YAML.
# Starts empty; appended as ambiguous cases surface.
OVERRIDES_PATH: Path = Path(
    os.environ.get("OVERRIDES_PATH", str(ARCHIVE_ROOT / "overrides.yaml"))
)


# --- Gamma discovery --------------------------------------------------------

# Polymarket US public gateway. No auth required for reads.
GAMMA_BASE: str = os.environ.get(
    "GAMMA_BASE", "https://gateway.polymarket.us"
)

# Tennis sport slug. Verified at startup against /v2/sports.
# Override if Polymarket renames the sport.
TENNIS_SPORT_SLUG: str = os.environ.get("TENNIS_SPORT_SLUG", "tennis")

# Gamma poll interval in seconds. 60s matches PM-Tennis's observed-safe cadence.
GAMMA_POLL_INTERVAL_SECONDS: int = int(
    os.environ.get("GAMMA_POLL_INTERVAL_SECONDS", "60")
)

# Per-page events limit on /v2/sports/{slug}/events pagination.
GAMMA_PAGE_LIMIT: int = int(os.environ.get("GAMMA_PAGE_LIMIT", "100"))

# HTTP client identity for the gateway. Cite the project so operators can
# trace back where the traffic is coming from.
USER_AGENT: str = (
    "latency-validation/phase2 "
    "(+https://github.com/peterlitton/latency-validation)"
)


# --- Polymarket Sports (Markets) WebSocket ----------------------------------

# Markets WS endpoint. Subscriptions are by market_slug.
# Documented cap: 100 slugs per subscription; use multiple subscriptions if more.
MARKETS_WS_URL: str = os.environ.get(
    "MARKETS_WS_URL", "wss://ws-subscriptions.polymarket.us/v2/markets"
)

# Max slugs per single subscription payload (Polymarket documented limit).
MARKETS_WS_SLUG_CAP: int = int(os.environ.get("MARKETS_WS_SLUG_CAP", "100"))

# Reconnect backoff: start, cap, factor.
WS_RECONNECT_INITIAL_SECONDS: float = float(
    os.environ.get("WS_RECONNECT_INITIAL_SECONDS", "1.0")
)
WS_RECONNECT_MAX_SECONDS: float = float(
    os.environ.get("WS_RECONNECT_MAX_SECONDS", "60.0")
)
WS_RECONNECT_FACTOR: float = float(os.environ.get("WS_RECONNECT_FACTOR", "2.0"))

# Per-worker supervision: how long to wait before restarting a crashed task.
WORKER_RESTART_DELAY_SECONDS: float = float(
    os.environ.get("WORKER_RESTART_DELAY_SECONDS", "5.0")
)

# Graceful shutdown deadline on SIGTERM — workers have this long to flush.
SHUTDOWN_GRACE_SECONDS: float = float(
    os.environ.get("SHUTDOWN_GRACE_SECONDS", "5.0")
)
