"""Envelope learning: split-conformal robust max-z (PRD 10.3, SYSTEM_DESIGN 7.2).

For machine m:
  1. quiet days Q: no error/maintenance/failure within +-margin days, telemetry 24/24 h on every
     channel, and outside the case window +-margin days (policy `all_except_case_window`);
  2. per channel: med_c and MAD_c over the hourly values of Q (MAD = 0 -> channel excluded);
     s_c = 1.4826 * MAD_c;
  3. day statistic T_d = max over channels and hours of |x - med_c| / s_c;
  4. T* = the k-th smallest T_d over Q, k = ceil((1 - alpha)(n + 1)).

TODO(M3): pooled T* / pooled scale for thin history (n < 19 / n < 10, they raise here, h0 shows
no machine needs them), the `before_only` policy, and the log-coverage refusal
(`LogCoverageError`, needs declared `coverage_period`s).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np

from trace_core.ids import envelope_id
from trace_core.models.case import Case
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle, Ontology
from trace_core.models.records import Envelope, QuietDay, Source
from trace_core.models.time import Interval
from trace_core.normalise.time import (
    MAX_TS,
    MIN_TS,
    days_between,
    hours_in,
    local_date,
    local_day_bounds,
)
from trace_core.ports import TelemetryReader
from trace_core.read.sensor import TS, telemetry_series_id
from trace_core.read.table import EVENT_ATTRIBUTE_NAMES

MAD_TO_SIGMA = 1.4826
"""Normal-consistency factor of the median absolute deviation (PRD 10.3)."""
QUIET_REASONS = ["no_event_within_margin", "telemetry_24_of_24", "outside_case_window"]
STATISTIC = "robust_max_z"


def robust_z(value: float, med: float, mad: float) -> float:
    """|x - med| / (1.4826 * MAD). Callers exclude degenerate channels (MAD = 0)."""
    return abs(value - med) / (MAD_TO_SIGMA * mad)


def conformal_rank(n: int, alpha: float) -> int:
    """k = ceil((1 - alpha)(n + 1)), exact in decimal (no float rounding at the boundary)."""
    return math.ceil((Decimal(1) - Decimal(str(alpha))) * (n + 1))


def event_days(events: Sequence[ClaimRecord], entity: str, tz: str) -> set[date]:
    out: set[date] = set()
    for claim in events:
        vt = claim.temporal.valid_time
        if (
            claim.subject.entity_id == entity
            and claim.attribute in EVENT_ATTRIBUTE_NAMES
            and isinstance(vt, Interval)
        ):
            out.add(local_date(vt.start, tz))
    return out


def _day_readings(
    data: dict[str, list[Any]], channels: list[str], tz: str
) -> dict[date, dict[str, dict[str, float]]]:
    """date -> channel -> {utc hour: reading}. Conflicting duplicates are dropped, never merged."""
    seen: dict[date, dict[str, dict[str, set[float]]]] = {}
    for index, ts in enumerate(data[TS]):
        day = local_date(str(ts), tz)
        for channel in channels:
            value = data[channel][index]
            if value is not None:
                per = seen.setdefault(day, {}).setdefault(channel, {})
                per.setdefault(str(ts), set()).add(float(value))
    return {
        day: {
            ch: {ts: next(iter(vals)) for ts, vals in per.items() if len(vals) == 1}
            for ch, per in chans.items()
        }
        for day, chans in seen.items()
    }


def learn_envelopes(
    telemetry: TelemetryReader,
    events: Sequence[ClaimRecord],
    sources: Sequence[Source],
    case: Case,
    ontology: Ontology,
    cfg: ConfigBundle,
) -> list[Envelope]:
    """Per machine. Raises NotImplementedError("M3") for the pooling fallbacks."""
    params = cfg.envelope
    if params.training_policy != "all_except_case_window":
        raise NotImplementedError("M3")  # before_only
    tz = cfg.case.plant_tz
    margin = timedelta(days=params.margin_days)
    case_days = days_between(case.window_start, case.window_end, tz)
    out: list[Envelope] = []
    for entity in sorted(case.entities):
        series = telemetry_series_id(entity)
        data = telemetry.read(series, MIN_TS, MAX_TS).to_pydict()
        channels = sorted(c for c in data if c != TS)
        by_day = _day_readings(data, channels, tz)
        events_on = event_days(events, entity, tz)
        quiet: list[date] = []
        for day in sorted(by_day):
            start, end = local_day_bounds(day, tz)
            expected = len(hours_in(start, end))
            full = all(len(by_day[day].get(ch, {})) == expected for ch in channels)
            near_event = any(abs(day - e) <= margin for e in events_on)
            near_case = any(abs(day - c) <= margin for c in case_days)
            if full and not near_event and not near_case:
                quiet.append(day)
        n = len(quiet)
        if n < params.min_quiet_days_own_t_star or n < params.min_quiet_days_own_scale:
            raise NotImplementedError("M3")  # thin history: pooling across the model
        med: dict[str, float] = {}
        mad: dict[str, float] = {}
        for ch in channels:
            values = np.array([v for d in quiet for v in by_day[d][ch].values()], dtype=float)
            med[ch] = float(np.median(values))
            mad[ch] = float(np.median(np.abs(values - med[ch])))
        degenerate = [ch for ch in channels if mad[ch] == 0.0]
        live = [ch for ch in channels if ch not in degenerate]
        t_d: dict[date, float] = {
            d: max(robust_z(v, med[ch], mad[ch]) for ch in live for v in by_day[d][ch].values())
            for d in quiet
        }
        ranked = sorted(t_d.values())
        k = conformal_rank(n, params.alpha)
        if k > n:
            raise NotImplementedError("M3")  # alpha too small for this n
        partition = {series: telemetry.partition_sha(series)}
        out.append(
            Envelope(
                envelope_id=envelope_id(
                    entity,
                    series,
                    channels,
                    STATISTIC,
                    "day",
                    [d.isoformat() for d in quiet],
                    params,
                    [],
                    partition,
                ),
                machine=entity,
                series_id=series,
                scope=channels,
                quiet_days=[
                    QuietDay(date=d.isoformat(), reasons=list(QUIET_REASONS), t_d=t_d[d])
                    for d in quiet
                ],
                n=n,
                med=med,
                mad=mad,
                T_star=ranked[k - 1],
                pooled="none",
                pool_members=[],
                degenerate_channels=degenerate,
                params=params,
                partition_hashes=partition,
            )
        )
    return out
