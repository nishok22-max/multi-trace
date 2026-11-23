"""Startup sweep (A-08): a build whose child died with the parent still says `running`. Any build
whose heartbeat is older than `max_age` is marked `failed_stale`, which frees the case's one build
slot and lets the same build key be retried (migration 003 only holds queued/running/done keys).
"""

from __future__ import annotations

from datetime import timedelta

from trace_adapters.sqlite.builds import BuildRepository
from trace_core.normalise.time import fmt_utc
from trace_core.ports import Clock

HEARTBEAT_SECONDS = 5
STALE_AFTER = timedelta(seconds=6 * HEARTBEAT_SECONDS)
"""Six missed 5-second heartbeats."""


def sweep_stale(repo: BuildRepository, clock: Clock, max_age: timedelta = STALE_AFTER) -> list[str]:
    """Mark stale builds; returns their ids (sorted)."""
    now = clock.now_utc()
    swept = repo.stale_in_flight(fmt_utc(now - max_age))
    for build_id in swept:
        repo.finish_failed(build_id, "failed_stale", "stale_heartbeat", fmt_utc(now))
    return swept
