"""Flatline detection (B-04, PRD 10.6, T-13).

A channel is *flat* where, over at least `flatline_min_hours` consecutive hourly readings, the
population variance is <= eps = `flatline_epsilon_factor` * s_c (s_c = 1.4826 * MAD of the
envelope). A degenerate channel (MAD = 0) has no scale, so eps is the absolute
`flatline_epsilon_factor`. A flat run becomes `GapClaim(flatline)`, so a frozen sensor can never
read as "normal"; unless a maintenance or failure event overlapping the run explains it (the
machine was stopped), in which case no gap is raised.

Missing hours break a run: runs are only built from consecutive hours.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.evidence import SensorWindowPointer
from trace_core.models.records import Envelope
from trace_core.models.time import Interval
from trace_core.normalise.envelopes import MAD_TO_SIGMA
from trace_core.normalise.time import HOUR, fmt_utc, parse_utc
from trace_core.read.sensor import RAW_STATISTIC, make_gap
from trace_core.stage_types import SensorWindows

STOP_EXPLAINING_ATTRIBUTES = frozenset({"maintenance_action", "failure_event"})
FLATLINE = "flatline"


def _variance(values: Sequence[float]) -> float:
    n = len(values)
    centre = sum(values) / n
    return sum((v - centre) ** 2 for v in values) / n


def flat_runs(readings: Sequence[tuple[str, float]], eps: float, min_hours: int) -> list[range]:
    """Index ranges (into `readings`, sorted by time) of maximal flat runs of consecutive hours."""
    runs: list[range] = []
    start = 0
    n = len(readings)
    while start < n:
        # one segment of consecutive hours
        stop = start + 1
        while stop < n and parse_utc(readings[stop][0]) - parse_utc(readings[stop - 1][0]) == HOUR:
            stop += 1
        i = start
        while i < stop:
            j = i + 1
            while j < stop and _variance([v for _, v in readings[i : j + 1]]) <= eps:
                j += 1
            if j - i >= min_hours:
                runs.append(range(i, j))
                i = j
            else:
                i += 1
        start = stop
    return runs


def _explained(events: Sequence[ClaimRecord], entity: str, start: str, end: str) -> bool:
    for event in events:
        vt = event.temporal.valid_time
        if (
            event.subject.entity_id == entity
            and event.attribute in STOP_EXPLAINING_ATTRIBUTES
            and isinstance(vt, Interval)
            and max(vt.start, start) < min(vt.end, end)
        ):
            return True
    return False


def detect_gaps(
    windows: SensorWindows,
    events: Sequence[ClaimRecord],
    envelopes: Sequence[Envelope],
    cfg: ConfigBundle,
) -> list[ClaimRecord]:
    params = cfg.envelope
    by_machine = {e.machine: e for e in envelopes}
    out: list[ClaimRecord] = []
    for window in sorted(windows.claims, key=lambda c: c.claim_id):
        ev = window.evidence
        entity = window.subject.entity_id
        if (
            not isinstance(ev, SensorWindowPointer)
            or ev.statistic != RAW_STATISTIC
            or entity is None
            or not isinstance(window.value, dict)
        ):
            continue
        env = by_machine.get(entity)
        if env is None:
            continue  # no envelope, no scale: nothing to compare a flatline against
        channel = ev.channels[0]
        mad = env.mad.get(channel, 0.0)
        scale = MAD_TO_SIGMA * mad
        eps = params.flatline_epsilon_factor * (scale if scale > 0.0 else 1.0)
        readings = sorted(
            (ts, float(v))
            for ts, v in window.value.items()
            if isinstance(v, float | int) and not isinstance(v, bool)
        )
        for run in flat_runs(readings, eps, params.flatline_min_hours):
            start = readings[run.start][0]
            end = fmt_utc(parse_utc(readings[run.stop - 1][0]) + HOUR)
            if _explained(events, entity, start, end):
                continue
            out.append(
                make_gap(
                    window,
                    entity,
                    channel,
                    FLATLINE,
                    start,
                    end,
                    len(run),
                    ev.series_id,
                    ev.partition_sha256,
                    cfg,
                )
            )
    return out
