"""Derived review status (B-10). Status is never stored (promise 6): it is a pure function of
(items, events, clock, calendar).

- `decided` / `stale`: the latest of an item's opened/decided/stale events (by `seq`);
- otherwise `open`;
- `escalated` appears iff the item is undecided and more than `escalation_working_days` working
  days have passed since `opened_at` (working weekdays minus holidays; dates in UTC because the
  calendar carries no zone).
`explained` events never change the status.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from trace_core.models.config import WorkingCalendar
from trace_core.models.records import ReviewEvent, ReviewItem, ReviewStatus
from trace_core.normalise.time import parse_utc
from trace_core.ports import Clock


def _is_working(day: date, calendar: WorkingCalendar) -> bool:
    return day.weekday() in calendar.working_weekdays and day.isoformat() not in calendar.holidays


def add_working_days(start: date, days: int, calendar: WorkingCalendar) -> date:
    """The date `days` working days after `start` (the start itself is not counted)."""
    if not calendar.working_weekdays:
        raise ValueError("calendar has no working weekdays")
    day = start
    remaining = days
    while remaining > 0:
        day += timedelta(days=1)
        if _is_working(day, calendar):
            remaining -= 1
    return day


def derive_review_status(
    items: Sequence[ReviewItem],
    events: Sequence[ReviewEvent],
    clock: Clock,
    calendar: WorkingCalendar,
) -> dict[str, ReviewStatus]:
    """open | decided | stale | escalated, derived at read time."""
    now = clock.now_utc()
    out: dict[str, ReviewStatus] = {}
    for item in items:
        mine = sorted((e for e in events if e.review_id == item.review_id), key=lambda e: e.seq)
        state = [e.kind for e in mine if e.kind in ("opened", "decided", "stale")]
        last = state[-1] if state else "opened"
        if last == "decided":
            out[item.review_id] = "decided"
            continue
        if last == "stale":
            out[item.review_id] = "stale"
            continue
        opened = parse_utc(item.opened_at)
        deadline_day = add_working_days(opened.date(), calendar.escalation_working_days, calendar)
        deadline = opened.replace(
            year=deadline_day.year, month=deadline_day.month, day=deadline_day.day
        )
        out[item.review_id] = "escalated" if now > deadline else "open"
    return out
