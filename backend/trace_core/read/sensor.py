"""Sensor reader (B-02/B-03 minimal). The only module allowed to aggregate readings (see
tools/check_no_mean.py); it still never averages: it keeps each hourly reading, takes a max where
a maximum is needed, and turns duplicate timestamps with different values into a gap.

For every plant-local day of the case window and every telemetry channel it emits one
day-window claim (EXTRACTED: it carries a `SensorWindowPointer`) whose structured value maps
each present hourly timestamp (UTC) to its reading. Missing hours and conflicting duplicates
become `GapClaim`s (`data_availability`), never a value (promise 4).

Flatline detection lives in normalise/gaps.py (it reuses `make_gap`). TODO(M3): the per-channel
series ids of the PRD gap example and shift-level windows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from trace_core.canonical import canonical_sha256
from trace_core.ids import build_claim
from trace_core.models.case import Case
from trace_core.models.claims import ClaimRecord, Confidence, Method, Subject
from trace_core.models.config import ConfigBundle
from trace_core.models.evidence import SensorWindowPointer
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.time import (
    day_interval,
    days_between,
    fmt_utc,
    hours_in,
    local_day_bounds,
    parse_utc,
)
from trace_core.ports import TelemetryReader
from trace_core.stage_types import SensorWindows

# Telemetry channel -> ontology attribute (the MS dataset's column names).
CHANNEL_ATTRIBUTE = {
    "volt": "voltage",
    "rotate": "rotation",
    "pressure": "pressure",
    "vibration": "vibration",
}
RAW_STATISTIC = "raw_hourly"
TS = "ts"


def telemetry_series_id(entity_id: str) -> str:
    return f"telemetry/{entity_id}"


def telemetry_source_id(entity_id: str) -> str:
    return "telemetry-" + entity_id.replace(":", "-")


def window_digest(
    series_id: str, channel: str, start: str, end: str, readings: dict[str, float]
) -> str:
    """Stand-in for the Arrow IPC slice hash: sha256 of the canonical slice content. The recheck
    (M3) recomputes exactly this from the Parquet partition."""
    return canonical_sha256(
        {
            "series_id": series_id,
            "channel": channel,
            "start": start,
            "end": end,
            "readings": sorted(readings.items()),
        }
    )


def _runs(hours: Sequence[str], missing: set[str]) -> list[tuple[str, str, int]]:
    """Contiguous runs of `missing` hours as (start, end, length), end exclusive."""
    runs: list[tuple[str, str, int]] = []
    run: list[str] = []
    for hour in hours:
        if hour in missing:
            run.append(hour)
            continue
        if run:
            runs.append((run[0], _next_hour(run[-1]), len(run)))
            run = []
    if run:
        runs.append((run[0], _next_hour(run[-1]), len(run)))
    return runs


def _next_hour(ts: str) -> str:
    from trace_core.normalise.time import HOUR

    return fmt_utc(parse_utc(ts) + HOUR)


def read_sensor(telemetry: TelemetryReader, case: Case, cfg: ConfigBundle) -> SensorWindows:
    windows: list[ClaimRecord] = []
    gaps: list[ClaimRecord] = []
    tz = cfg.case.plant_tz
    for entity in sorted(case.entities):
        series = telemetry_series_id(entity)
        partition = telemetry.partition_sha(series)
        for day in days_between(case.window_start, case.window_end, tz):
            got_windows, got_gaps = _day(telemetry, series, partition, entity, day, case, cfg)
            windows.extend(got_windows)
            gaps.extend(got_gaps)
    return SensorWindows(claims=windows, gap_claims=gaps)


def _day(
    telemetry: TelemetryReader,
    series: str,
    partition: str,
    entity: str,
    day: date,
    case: Case,
    cfg: ConfigBundle,
) -> tuple[list[ClaimRecord], list[ClaimRecord]]:
    tz = cfg.case.plant_tz
    start, end = local_day_bounds(day, tz)
    expected = hours_in(start, end)
    data = telemetry.read(series, start, end).to_pydict()
    channels = sorted(c for c in data if c != TS)
    interval = day_interval(day, tz, "computed_window")
    subject = Subject(entity_id=entity, link_status="resolved")
    windows: list[ClaimRecord] = []
    gaps: list[ClaimRecord] = []
    for channel in channels:
        seen: dict[str, set[float]] = {}
        for ts, value in zip(data[TS], data[channel], strict=True):
            if value is not None:
                seen.setdefault(ts, set()).add(float(value))
        readings = {h: next(iter(seen[h])) for h in expected if len(seen.get(h, ())) == 1}
        conflicting = {h for h in expected if len(seen.get(h, ())) > 1}
        missing = {h for h in expected if h not in seen}
        coverage = len(readings) / len(expected) if expected else 0.0
        attribute = CHANNEL_ATTRIBUTE.get(channel, channel)
        pointer = SensorWindowPointer(
            source_id=telemetry_source_id(entity),
            series_id=series,
            partition_sha256=partition,
            channels=[channel],
            start=start,
            end=end,
            n_points=len(readings),
            expected_points=len(expected),
            statistic=RAW_STATISTIC,
            granularity="day",
            window_sha256=window_digest(series, channel, start, end, readings),
        )
        window = build_claim(
            case_id=case.case_id,
            claim_type="extracted",
            statement=(
                f"{channel} readings of {entity} on {day:%d %b %Y}: "
                f"{len(readings)} of {len(expected)} hours present (sensor units, undocumented)"
            ),
            subject=subject,
            attribute=attribute,
            value=dict(sorted(readings.items())),
            value_type="structured",
            unit=None,
            unit_status="sensor_native",
            temporal=Temporal(
                valid_time=interval,
                observed_time=ObservedTime(at=end, basis="sensor_timestamp"),
                timezone_original=tz,
            ),
            modality="sensor",
            evidence=pointer,
            derived_from=[],
            method=Method(extractor="sensor_window", extractor_version="1", rule_id="window.day"),
            confidence=Confidence(
                value=coverage,
                calibrated=False,
                components={"coverage": coverage},
                stage="pre",
                note="uncalibrated: the fraction of expected hourly readings that are present",
            ),
        )
        windows.append(window)
        for kind, hours in (("missing", missing), ("conflicting_readings", conflicting)):
            for run_start, run_end, length in _runs(expected, hours):
                gaps.append(
                    make_gap(
                        window,
                        entity,
                        channel,
                        kind,
                        run_start,
                        run_end,
                        length,
                        series,
                        partition,
                        cfg,
                    )
                )
    return windows, gaps


def make_gap(
    window: ClaimRecord,
    entity: str,
    channel: str,
    kind: str,
    start: str,
    end: str,
    length: int,
    series: str,
    partition: str,
    cfg: ConfigBundle,
) -> ClaimRecord:
    tz = cfg.case.plant_tz
    return build_claim(
        case_id=window.case_id,
        claim_type="inferred",
        statement=(
            f"{channel} of {entity}: {length} h {kind.replace('_', ' ')}; "
            "no data is never read as normal"
        ),
        subject=Subject(entity_id=entity, link_status="resolved"),
        attribute="data_availability",
        value=kind,
        value_type="categorical",
        unit=None,
        unit_status="not_applicable",
        temporal=Temporal(
            valid_time=Interval(
                start=start, end=end, granularity="hour", resolved_from="computed_window"
            ),
            observed_time=ObservedTime(at=end, basis="sensor_timestamp"),
            timezone_original=tz,
        ),
        modality="sensor",
        evidence=SensorWindowPointer(
            source_id=telemetry_source_id(entity),
            series_id=f"{series}/{channel}",
            partition_sha256=partition,
            channels=[channel],
            start=start,
            end=end,
            n_points=0,
            expected_points=length,
            statistic=f"gap_{kind}",
            granularity="hour",
            window_sha256=canonical_sha256(
                {"series": series, "channel": channel, "kind": kind, "start": start, "end": end}
            ),
        ),
        derived_from=[window.claim_id],
        method=Method(extractor="gap_detector", extractor_version="1", rule_id=f"gap.{kind}"),
        confidence=Confidence(value=1.0, calibrated=False, components={}, stage="pre"),
    )
