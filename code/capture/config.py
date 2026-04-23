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

# Cross-feed overrides: maps API-Tennis event_key (int) to Polymarket-owned
# match_id (str). Added in session 3.1 per Q2 decision: manual curation, no
# fuzzy matching in Phase 3. See docs/cross_feed_overrides.md for format.
CROSS_FEED_OVERRIDES_PATH: Path = Path(
    os.environ.get(
        "CROSS_FEED_OVERRIDES_PATH",
        str(ARCHIVE_ROOT / "cross_feed_overrides.yaml"),
    )
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

# The Markets WS is accessed via the official polymarket-us SDK (pinned 0.1.2
# in pyproject.toml). URL and Ed25519 handshake signing are handled by the
# SDK; we only configure credentials and batching.

# Polymarket US API credentials. Ed25519-based auth; key_id is a UUID;
# secret_key is a base64-encoded Ed25519 private key. Never committed.
POLYMARKET_US_API_KEY_ID: str = os.environ.get("POLYMARKET_US_API_KEY_ID", "")
POLYMARKET_US_API_SECRET_KEY: str = os.environ.get(
    "POLYMARKET_US_API_SECRET_KEY", ""
)

# Max slugs per single subscribe call (Polymarket-documented 100 limit).
# Larger active sets span multiple connections.
MARKETS_WS_SLUG_CAP: int = int(os.environ.get("MARKETS_WS_SLUG_CAP", "100"))

# Reconnect backoff: start, cap, factor. Shared between Polymarket and
# API-Tennis workers — same transport-level semantics.
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


# --- API-Tennis WebSocket ---------------------------------------------------

# API-Tennis API key, query-string auth. Business trial through ~May 7 2026;
# 14-day measurement clock starts at first use. Unlike Polymarket's handshake
# auth, API-Tennis just appends ?APIkey=... to the WSS URL.
API_TENNIS_KEY: str = os.environ.get("API_TENNIS_KEY", "")

# Base WebSocket URL. Key + timezone appended at connect time.
API_TENNIS_WS_BASE: str = os.environ.get(
    "API_TENNIS_WS_BASE", "wss://wss.api-tennis.com/live"
)

# Timezone for event_time / event_date fields in received messages. UTC
# keeps everything aligned with Polymarket's timestamps and with
# arrived_at_ms (captured at handler entry). Overrideable for debugging.
API_TENNIS_TIMEZONE: str = os.environ.get("API_TENNIS_TIMEZONE", "UTC")

# Reconnect backoff reuses the same WS_RECONNECT_* constants as Polymarket
# — no API-Tennis-specific overrides. If cadence characteristics diverge
# (e.g., API-Tennis kicks clients more aggressively), add dedicated
# constants then. For now: single set.
