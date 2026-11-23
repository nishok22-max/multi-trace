"""B-04: flatline detection (T-13). Named tests: test_frozen_sensor_flatline,
test_stop_event_not_gap, test_flatline_degenerate_scale_abs_eps, test_spike_in_gap_never_agree."""

from __future__ import annotations

from datetime import timedelta

from tests.factories import CASE_ID, sha
from trace_adapters.config_loader import load_config_bundle
from trace_core.canonical import canonical_sha256
from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord, Confidence, Method, Subject
from trace_core.models.evidence import SensorWindowPointer, TableCellPointer
from trace_core.models.records import Envelope
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.gaps import detect_gaps, flat_runs
from trace_core.normalise.sensor_state import derive_sensor_state
from trace_core.normalise.time import fmt_utc, hour_interval, parse_utc
from trace_core.read.sensor import RAW_STATISTIC, window_digest
from trace_core.stage_types import SensorWindows

CFG = load_config_bundle()
ENTITY = "machine:21"
SERIES = "telemetry/machine:21"
DAY_START = "2015-08-04T18:30:00Z"
DAY_END = "2015-08-05T18:30:00Z"


def _hours(n: int = 24) -> list[str]:
    start = parse_utc(DAY_START)
    return [fmt_utc(start + timedelta(hours=i)) for i in range(n)]


def _window(channel: str, values: dict[str, float]) -> ClaimRecord:
    return build_claim(
        case_id=CASE_ID,
        claim_type="extracted",
        statement=f"{channel} readings",
        subject=Subject(entity_id=ENTITY, link_status="resolved"),
        attribute=channel,
        value=dict(sorted(values.items())),
        value_type="structured",
        unit=None,
        unit_status="sensor_native",
        temporal=Temporal(
            valid_time=Interval(
                start=DAY_START, end=DAY_END, granularity="day", resolved_from="computed_window"
            ),
            observed_time=ObservedTime(at=DAY_END, basis="sensor_timestamp"),
            timezone_original=CFG.case.plant_tz,
        ),
        modality="sensor",
        evidence=SensorWindowPointer(
            source_id="telemetry-machine-21",
            series_id=SERIES,
            partition_sha256=sha("partition"),
            channels=[channel],
            start=DAY_START,
            end=DAY_END,
            n_points=len(values),
            expected_points=24,
            statistic=RAW_STATISTIC,
            granularity="day",
            window_sha256=window_digest(SERIES, channel, DAY_START, DAY_END, values),
        ),
        derived_from=[],
        method=Method(extractor="sensor_window", extractor_version="1", rule_id="window.day"),
        confidence=Confidence(value=1.0, calibrated=False, components={}, stage="pre"),
    )


def _envelope(channel: str, mad: float) -> Envelope:
    return Envelope(
        envelope_id="env_" + "0" * 24,
        machine=ENTITY,
        series_id=SERIES,
        scope=[channel],
        quiet_days=[],
        n=0,
        med={channel: 100.0},
        mad={channel: mad},
        T_star=3.0,
        pooled="none",
        pool_members=[],
        degenerate_channels=[] if mad > 0 else [channel],
        params=CFG.envelope,
        partition_hashes={SERIES: sha("partition")},
    )


def _event(attribute: str, at: str) -> ClaimRecord:
    return build_claim(
        case_id=CASE_ID,
        claim_type="extracted",
        statement=f"{attribute} at {at}",
        subject=Subject(entity_id=ENTITY, link_status="resolved"),
        attribute=attribute,
        value="x",
        value_type="categorical",
        unit=None,
        unit_status="not_applicable",
        temporal=Temporal(
            valid_time=hour_interval(at, "explicit"),
            observed_time=ObservedTime(at=at, basis="sensor_timestamp"),
            timezone_original=CFG.case.plant_tz,
        ),
        modality="table",
        evidence=TableCellPointer(
            source_id="src-log",
            sha256=sha("log"),
            row=0,
            column="comp",
            raw_value="x",
            row_sha256=sha("row"),
            row_byte_offset=0,
        ),
        derived_from=[],
        method=Method(extractor="csv:event_log", extractor_version="1", rule_id="table.x"),
        confidence=Confidence(value=0.9, calibrated=False, components={}, stage="pre"),
    )


def _readings(frozen_from: int, frozen_to: int) -> dict[str, float]:
    hours = _hours()
    return {
        h: (100.0 if frozen_from <= i < frozen_to else 100.0 + (i % 5) + 0.37 * i)
        for i, h in enumerate(hours)
    }


def _gaps(values: dict[str, float], mad: float = 5.0, events: list[ClaimRecord] | None = None):
    windows = SensorWindows(claims=[_window("vibration", values)])
    return detect_gaps(windows, events or [], [_envelope("vibration", mad)], CFG)


def test_frozen_sensor_flatline() -> None:
    gaps = _gaps(_readings(6, 14))  # 8 frozen hours >= flatline_min_hours
    assert [g.value for g in gaps] == ["flatline"]
    gap = gaps[0]
    assert gap.attribute == "data_availability"
    assert isinstance(gap.evidence, SensorWindowPointer)
    assert gap.evidence.expected_points == 8
    assert gap.evidence.start == _hours()[6] and gap.evidence.end == _hours()[14]


def test_short_flat_run_is_not_a_flatline() -> None:
    assert _gaps(_readings(6, 11)) == []  # 5 h < 6 h


def test_noisy_signal_has_no_flatline() -> None:
    assert _gaps(_readings(0, 0)) == []


def test_missing_hour_breaks_a_run() -> None:
    values = _readings(6, 14)
    del values[_hours()[10]]
    assert _gaps(values) == []  # 4 h + 3 h, neither reaches 6 h


def test_stop_event_not_gap() -> None:
    event = _event("maintenance_action", _hours()[9])
    assert _gaps(_readings(6, 14), events=[event]) == []


def test_error_event_does_not_explain_a_flatline() -> None:
    event = _event("error_event", _hours()[9])
    assert len(_gaps(_readings(6, 14), events=[event])) == 1


def test_flatline_degenerate_scale_abs_eps() -> None:
    """MAD = 0 gives no scale: eps falls back to the absolute epsilon factor."""
    assert len(_gaps(_readings(6, 14), mad=0.0)) == 1
    near = _readings(6, 14)
    near[_hours()[8]] = 101.0  # variance is in squared units; 1.0 is far above the 1e-6 floor
    assert _gaps(near, mad=0.0) == []


def test_flat_runs_are_maximal_and_deterministic() -> None:
    hours = _hours(10)
    readings = [(h, 5.0) for h in hours]
    assert flat_runs(readings, 1e-9, 6) == [range(0, 10)]
    assert flat_runs(readings, 1e-9, 11) == []


def test_flatline_hours_do_not_count_as_coverage() -> None:
    """A frozen channel gives a partial day, so a forall 'ran normally' cannot agree (promise 4)."""
    values = _readings(6, 14)
    window = _window("vibration", values)
    env = _envelope("vibration", 5.0)
    windows = SensorWindows(claims=[window])
    flat = SensorWindows(claims=[window], gap_claims=detect_gaps(windows, [], [env], CFG))
    plain = derive_sensor_state(windows, [env], CFG)[0]
    frozen = derive_sensor_state(flat, [env], CFG)[0]
    assert isinstance(plain.evidence, SensorWindowPointer)
    assert isinstance(frozen.evidence, SensorWindowPointer)
    assert plain.evidence.n_points == 24
    assert frozen.evidence.n_points == 24 - 8
    assert canonical_sha256(frozen.value) is not None
