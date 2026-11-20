"""Time models. Half-open [start, end), fixed-width UTC strings (promise 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from trace_core.models.base import CoreModel

_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d Z$".replace(" ", "")


def _check_calendar(value: str) -> str:
    try:
        datetime.fromisoformat(value[:-1])
    except ValueError as exc:
        raise ValueError("not a real calendar date/time") from exc
    return value


UtcStr = Annotated[str, StringConstraints(pattern=_UTC_PATTERN), AfterValidator(_check_calendar)]
"""Exactly `YYYY-MM-DDTHH:MM:SSZ`. String order equals time order."""

Granularity = Literal["hour", "shift", "day"]


class Interval(CoreModel):
    """Half-open valid-time interval `[start, end)`."""

    start: UtcStr
    end: UtcStr
    granularity: Granularity
    resolved_from: str

    @model_validator(mode="after")
    def _start_before_end(self) -> Interval:
        if not self.start < self.end:
            raise ValueError("interval requires start < end (half-open)")
        return self


class UnknownTime(CoreModel):
    """No document date. Deliberately has no bounds (file mtime is never used)."""

    granularity: Literal["unknown"] = "unknown"
    reason: str


class ObservedTime(CoreModel):
    """When the claim was observed. `file_timestamp` is not allowed (promise 7)."""

    at: UtcStr | None = None
    basis: Literal["document_date", "sensor_timestamp", "ingest_time"]


ValidTime = Annotated[Interval | UnknownTime, Field(discriminator="granularity")]


class Temporal(CoreModel):
    valid_time: ValidTime
    observed_time: ObservedTime
    timezone_original: str | None = None

    @model_validator(mode="after")
    def _unknown_iff_unknown(self) -> Temporal:
        is_unknown = isinstance(self.valid_time, UnknownTime)
        if is_unknown != (self.valid_time.granularity == "unknown"):
            raise ValueError("UnknownTime <=> granularity 'unknown'")
        return self
