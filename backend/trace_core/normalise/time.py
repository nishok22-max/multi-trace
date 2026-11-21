"""Time helpers (PRD 10.2): half-open `[start, end)` intervals, fixed-width UTC strings, days in
the case's `plant_tz`. File mtime is never an input. Only `resolve_time` (M3) is still a stub."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.time import Interval

MIN_TS = "0001-01-01T00:00:00Z"
"""Lower bound for full-history reads (fixed width, sorts before every real timestamp)."""
MAX_TS = "9999-12-31T23:59:59Z"
HOUR = timedelta(hours=1)
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def parse_utc(value: str) -> datetime:
    """`YYYY-MM-DDTHH:MM:SSZ` -> aware UTC datetime."""
    return datetime.strptime(value, _FMT).replace(tzinfo=UTC)


def fmt_utc(value: datetime) -> str:
    """Aware datetime -> fixed-width UTC string."""
    return value.astimezone(UTC).strftime(_FMT)


def local_day_bounds(day: date, tz: str) -> tuple[str, str]:
    """Half-open `[D 00:00, D+1 00:00)` in `tz`, as UTC strings."""
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time(0, 0), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=zone)
    return fmt_utc(start), fmt_utc(end)


def day_interval(day: date, tz: str, resolved_from: str) -> Interval:
    start, end = local_day_bounds(day, tz)
    return Interval(start=start, end=end, granularity="day", resolved_from=resolved_from)


def hour_interval(start_utc: str, resolved_from: str) -> Interval:
    end = fmt_utc(parse_utc(start_utc) + HOUR)
    return Interval(start=start_utc, end=end, granularity="hour", resolved_from=resolved_from)


def local_date(utc: str, tz: str) -> date:
    """Plant-local calendar date of a UTC instant."""
    return parse_utc(utc).astimezone(ZoneInfo(tz)).date()


def local_naive_to_utc(naive: datetime, tz: str) -> str:
    """A naive plant-local timestamp (dataset convention, assumption A7) -> UTC string.
    Ambiguous or non-existent local times are refused (fail closed)."""
    if naive.tzinfo is not None:
        raise ValueError("expected a naive plant-local timestamp")
    zone = ZoneInfo(tz)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("ambiguous or non-existent local time")
    return fmt_utc(first)


def local_hhmm(utc: str, tz: str) -> str:
    return parse_utc(utc).astimezone(ZoneInfo(tz)).strftime("%H:%M")


def days_between(start_utc: str, end_utc: str, tz: str) -> list[date]:
    """Plant-local dates touched by the half-open window `[start, end)`."""
    first = local_date(start_utc, tz)
    last = local_date(fmt_utc(parse_utc(end_utc) - timedelta(seconds=1)), tz)
    out: list[date] = []
    cursor = first
    while cursor <= last:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def hours_in(start_utc: str, end_utc: str) -> list[str]:
    """Expected hourly grid inside `[start, end)` (cadence 1 h, PRD 10.6)."""
    out: list[str] = []
    cursor = parse_utc(start_utc)
    end = parse_utc(end_utc)
    while cursor < end:
        out.append(fmt_utc(cursor))
        cursor += HOUR
    return out


def resolve_time(claims: list[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    raise NotImplementedError("M3")
