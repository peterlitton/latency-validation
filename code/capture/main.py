"""Capture orchestrator.

Runs the discovery loop, Sports WS worker, and API-Tennis WS worker as
concurrent supervised tasks. Session 3.1 adds the third worker.

Supervision model:
  - Each worker runs inside `supervise(name, factory)`, which catches any
    exception that bubbles out, logs it, waits WORKER_RESTART_DELAY_SECONDS,
    then restarts the worker.
  - asyncio.CancelledError is treated specially — it means graceful
    shutdown, so we propagate instead of restarting.

Shutdown model:
  - SIGTERM (Render sends this on deploy/restart) and SIGINT trigger a
    shutdown event.
  - Main coroutine waits for either all workers to finish OR the shutdown
    event to fire.
  - On shutdown, we cancel the worker tasks and wait up to
    SHUTDOWN_GRACE_SECONDS for them to finish flushing.
  - Because JSONL writes are synchronous and line-buffered, the worst case
    for a hard kill is losing one half-written record; earlier records are
    durable.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Awaitable, Callable

from .api_tennis_ws import ApiTennisWorker
from .config import (
    SHUTDOWN_GRACE_SECONDS,
    TENNIS_SPORT_SLUG,
    WORKER_RESTART_DELAY_SECONDS,
)
from .discovery import DiscoveryLoop, GammaClient, verify_sport_slug
from .sports_ws import SportsWorker

log = logging.getLogger("capture.orchestrator")


async def supervise(
    name: str,
    factory: Callable[[], Awaitable[None]],
) -> None:
    """Run a long-running worker coroutine, restart on unexpected crashes.

    `factory` returns a fresh awaitable each call so we can restart the
    worker cleanly after a crash.
    """
    while True:
        try:
            log.info("[supervisor:%s] starting worker", name)
            await factory()
            # Clean return means the worker decided to stop — unusual for
            # long-running workers but allow it to exit gracefully.
            log.info("[supervisor:%s] worker exited cleanly", name)
            return
        except asyncio.CancelledError:
            log.info("[supervisor:%s] cancelled; propagating", name)
            raise
        except Exception as exc:  # noqa: BLE001 — supervision is the point
            log.exception(
                "[supervisor:%s] worker crashed (%s); restarting in %.1fs",
                name,
                exc.__class__.__name__,
                WORKER_RESTART_DELAY_SECONDS,
            )
            await asyncio.sleep(WORKER_RESTART_DELAY_SECONDS)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def _install_shutdown_handlers(loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
    """Wire SIGTERM/SIGINT to set the shutdown event.

    Best-effort: add_signal_handler works on POSIX. If we're on a platform
    that doesn't support it (Windows), we fall back to default KeyboardInterrupt.
    """
    def _trigger(signame: str) -> None:
        log.info("Received %s; triggering graceful shutdown", signame)
        event.set()

    for signame in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(
                getattr(signal, signame), _trigger, signame
            )
        except (NotImplementedError, AttributeError):
            pass


async def run() -> None:
    """Main entry point."""
    _setup_logging()
    log.info("Capture orchestrator starting (Phase 3, session 3.1 scope).")

    # Verify the Gamma sport slug on startup. Non-fatal if it fails —
    # polls will just return empty, visible in logs. This matches the
    # PM-Tennis convention (discovery.py verify_sport_slug).
    gamma = GammaClient()
    try:
        await verify_sport_slug(gamma, TENNIS_SPORT_SLUG)
    except Exception as exc:  # noqa: BLE001 — startup diagnostic only
        log.warning("Sport-slug verification raised: %s (continuing)", exc)

    discovery = DiscoveryLoop(gamma)
    sports = SportsWorker(discovery)
    api_tennis = ApiTennisWorker()

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_shutdown_handlers(loop, shutdown)

    # Launch supervised workers.
    tasks = [
        asyncio.create_task(
            supervise("discovery", discovery.run_forever),
            name="supervise.discovery",
        ),
        asyncio.create_task(
            supervise("sports_ws", sports.run_forever),
            name="supervise.sports_ws",
        ),
        asyncio.create_task(
            supervise("api_tennis_ws", api_tennis.run_forever),
            name="supervise.api_tennis_ws",
        ),
    ]

    # Wait until either a supervisor exits (shouldn't happen — supervisors
    # run forever) or the shutdown signal fires.
    shutdown_task = asyncio.create_task(
        shutdown.wait(), name="shutdown_waiter"
    )
    done, _pending = await asyncio.wait(
        [*tasks, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Graceful shutdown: cancel everything and give workers a grace window
    # to flush.
    log.info("Entering shutdown; cancelling workers.")
    for t in tasks:
        t.cancel()
    shutdown_task.cancel()

    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=SHUTDOWN_GRACE_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning(
            "Shutdown grace window (%.1fs) elapsed; some workers "
            "did not cancel in time.",
            SHUTDOWN_GRACE_SECONDS,
        )

    await gamma.aclose()
    log.info("Capture orchestrator stopped.")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        # Only reached if signal handlers weren't installed successfully.
        log.info("KeyboardInterrupt; exiting.")


if __name__ == "__main__":
    main()
