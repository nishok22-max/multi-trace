"""Derived review status (stage signature only). Status is never stored (promise 6)."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.config import WorkingCalendar
from trace_core.models.records import ReviewEvent, ReviewItem, ReviewStatus
from trace_core.ports import Clock


def derive_review_status(
    items: Sequence[ReviewItem],
    events: Sequence[ReviewEvent],
    clock: Clock,
    calendar: WorkingCalendar,
) -> dict[str, ReviewStatus]:
    """open | decided | stale | escalated, derived at read time."""
    raise NotImplementedError("M2/M3")
