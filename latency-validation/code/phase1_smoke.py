"""Phase 1 deploy smoke test.

Run on the provisioned PaaS host. Verifies:
- Python 3.12 runtime.
- Persistent disk is writable at the expected archive path.
- Env var store is accessible (keys may be empty at Phase 1; presence is not checked).

Exits 0 on success, nonzero on failure. Intended to be run as the PaaS's
start command for the Phase 1 deploy and then replaced by real workers in Phase 2.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT", "/data/archive"))
EXPECTED_ENV_KEYS = (
    "API_TENNIS_KEY",
    "POLYMARKET_US_API_KEY_ID",
    "POLYMARKET_US_API_SECRET_KEY",
)


def check_python_version() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 12):
        raise RuntimeError(
            f"Python 3.12+ required; got {major}.{minor}"
        )
    print(f"[ok] Python {sys.version.split()[0]}")


def check_archive_disk() -> None:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    # Write-then-read a probe file to confirm the mount is actually writable.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=ARCHIVE_ROOT, delete=False, suffix=".probe"
    ) as f:
        probe_path = Path(f.name)
        f.write(datetime.now(UTC).isoformat())
    probe_path.read_text()
    probe_path.unlink()
    print(f"[ok] archive disk writable at {ARCHIVE_ROOT}")


def check_env_var_store() -> None:
    # Phase 1 does not require keys to be set — just that the env var store is
    # readable. Report presence without printing values.
    present = [k for k in EXPECTED_ENV_KEYS if os.environ.get(k)]
    missing = [k for k in EXPECTED_ENV_KEYS if not os.environ.get(k)]
    print(f"[ok] env var store readable; {len(present)} set, {len(missing)} unset")
    if missing:
        print(f"     unset (expected to be set by Phase 2/3): {', '.join(missing)}")


def main() -> int:
    print("Phase 1 smoke test starting...")
    try:
        check_python_version()
        check_archive_disk()
        check_env_var_store()
    except Exception as e:  # noqa: BLE001 — smoke test wants the one-line reason
        print(f"[fail] {e}")
        return 1
    print("Phase 1 smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
