"""Time helpers (PRD 10.2): half-open `[start, end)` intervals, fixed-width UTC strings, days in
the case's `plant_tz`. File mtime is never an input.
Relative expressions are resolved by `resolve_time`."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.time import Interval, Temporal, UnknownTime

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


_RELATIVE_DAYS = {"yesterday": -1, "today": 0, "tomorrow": 1}
_SHIFT = re.compile(r"\bshift[ _-]?(\d+)\b", re.IGNORECASE)


def shift_interval(
    day: date, start_hour: int, end_hour: int, tz: str, resolved_from: str
) -> Interval:
    """`[D start_hour:00, D end_hour:00)` in plant-local time (24 = next midnight)."""
    zone = ZoneInfo(tz)
    start = datetime.combine(day, time(start_hour % 24), tzinfo=zone)
    if start_hour >= 24:
        start += timedelta(days=start_hour // 24)
    end = datetime.combine(day + timedelta(days=end_hour // 24), time(end_hour % 24), tzinfo=zone)
    return Interval(
        start=fmt_utc(start), end=fmt_utc(end), granularity="shift", resolved_from=resolved_from
    )


def _relative(claim: ClaimRecord, cfg: ConfigBundle) -> Interval | None:
    """Resolve "yesterday" / "today" (+ optional "shift N") against the document's observed
    time, in plant-local days. No document date -> None (time stays unknown, promise 7)."""
    observed = claim.temporal.observed_time.at
    if observed is None or claim.temporal.observed_time.basis != "document_date":
        return None
    text = claim.statement.casefold()
    offsets = [(w, o) for w, o in _RELATIVE_DAYS.items() if re.search(rf"\b{w}\b", text)]
    if len(offsets) != 1:
        return None  # none, or ambiguous: fail closed
    tz = cfg.case.plant_tz
    day = local_date(observed, tz) + timedelta(days=offsets[0][1])
    shift_match = _SHIFT.search(claim.statement)
    if shift_match is not None:
        index = int(shift_match.group(1)) - 1
        if not 0 <= index < len(cfg.case.shifts):
            return None
        shift = cfg.case.shifts[index]
        return shift_interval(day, shift.start_hour, shift.end_hour, tz, "relative")
    return day_interval(day, tz, "relative")


def resolve_time(claims: list[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    """Fill the valid time of text claims whose date is relative to the document date.
    Everything already dated, and everything without a document date, is left unchanged."""
    out: list[ClaimRecord] = []
    for claim in claims:
        if claim.modality != "text" or not isinstance(claim.temporal.valid_time, UnknownTime):
            out.append(claim)
            continue
        interval = _relative(claim, cfg)
        if interval is None:
            out.append(claim)
            continue
        fields = claim.model_dump(mode="python")
        fields["temporal"] = Temporal(
            valid_time=interval,
            observed_time=claim.temporal.observed_time,
            timezone_original=claim.temporal.timezone_original,
        )
        out.append(build_claim(**fields))
    return out
