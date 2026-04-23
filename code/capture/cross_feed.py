"""Cross-feed match identity resolver.

Maps API-Tennis `event_key` (int) to the Polymarket-owned canonical
`match_id` (str) via an operator-curated YAML file. Session 3.1 scope
decision (plan §5.4 + operator Q2 answer): manual curation only, no
fuzzy matching. The Polymarket worker establishes match identity at
discovery time; API-Tennis events route to that already-established
match_id by explicit mapping.

File format (cross_feed_overrides.yaml):

    # Comments welcome. Edited by the operator as matches appear.
    # Format:
    #   <api_tennis_event_key>: <polymarket_match_id>
    12121266: madrid-open_daniel-merida-aguilar_marco-trungelliti_2026-04-23
    12121257: challenger-savannah_aidan-mayo_andres-andrade_2026-04-23

The mapping is one-way: API-Tennis event_key -> Polymarket match_id. If a
Polymarket match doesn't have a corresponding API-Tennis event_key (or
hasn't been curated yet), its API-Tennis events land in the `_unresolved`
sub-tree and the operator can curate later. Unresolved events are not
lost; just not yet routed to a shared match directory.

Reloading:
  The file is re-read on each worker reconnect cycle (same pattern as
  overrides.yaml for the Polymarket resolver). Operator can add an
  entry mid-match and the next reconnect picks it up; there is no
  explicit "reload" signal.

Future scope (flagged, not built):
  Fuzzy matching on tournament + last-name-initial + date would let the
  worker auto-suggest overrides for operator confirmation. Deferred per
  Q2 decision — not needed for the 14-day measurement window's ~60-90
  Madrid matches plus whatever Challengers are in play.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from .config import CROSS_FEED_OVERRIDES_PATH


log = logging.getLogger("capture.cross_feed")


def load_overrides(path: Optional[Path] = None) -> dict[int, str]:
    """Load event_key -> match_id overrides from YAML.

    Returns an empty dict if the file doesn't exist, is empty, or fails to
    parse. Parse failures are logged but non-fatal — the worker keeps
    running, routing everything to _unresolved until the file is fixed.

    Keys must be integer event_keys. If the YAML contains string keys
    (operator typo like `"12121266"` instead of `12121266`), we coerce
    to int when possible and warn on failures.
    """
    target = path or CROSS_FEED_OVERRIDES_PATH

    if not target.exists():
        log.info("Cross-feed overrides file not present at %s", target)
        return {}

    try:
        raw = yaml.safe_load(target.read_text()) or {}
    except yaml.YAMLError as exc:
        log.error("Cross-feed overrides YAML parse error: %s", exc)
        return {}

    if not isinstance(raw, dict):
        log.error(
            "Cross-feed overrides: expected top-level dict, got %s",
            type(raw).__name__,
        )
        return {}

    out: dict[int, str] = {}
    for k, v in raw.items():
        if isinstance(k, int):
            key_int = k
        else:
            try:
                key_int = int(str(k))
            except (TypeError, ValueError):
                log.warning(
                    "Cross-feed overrides: skipping non-int key %r "
                    "(value was %r); fix the YAML",
                    k,
                    v,
                )
                continue
        if not isinstance(v, str) or not v.strip():
            log.warning(
                "Cross-feed overrides: skipping non-string or empty "
                "value for key %r (got %r)",
                k,
                v,
            )
            continue
        out[key_int] = v.strip()

    log.info(
        "Loaded %d cross-feed override(s) from %s",
        len(out),
        target,
    )
    return out


def match_id_for_event_key(
    event_key: int,
    overrides: dict[int, str],
) -> Optional[str]:
    """Return the mapped match_id for an event_key, or None if unresolved.

    Thin wrapper to keep the routing call-site self-documenting. Future
    fuzzy-matching logic would plug in here without changing the worker.
    """
    return overrides.get(event_key)
