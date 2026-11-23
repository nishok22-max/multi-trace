"""B-05: units are never guessed. Named: test_gauge_vs_telemetry_cannot_compare,
test_unknown_unit_never_converts (test_no_mm_s_in_api_or_ui belongs to M4/UI)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tests.factories import CASE_ID, sha
from tests.unit.engine.test_gaps import CFG, DAY_END, DAY_START, ENTITY, SERIES, _window
from trace_core.compare.gate import gate
from trace_core.ids import build_claim, config_hash, verify_claim
from trace_core.models.claims import ClaimRecord, Confidence, Method, Subject
from trace_core.models.evidence import TableCellPointer
from trace_core.models.records import Envelope
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.units import convert, normalise_units
from trace_core.stage_types import GateContext


def _gauge(value: float, unit: str | None, status: str = "known") -> ClaimRecord:
    fields: dict[str, Any] = {
        "case_id": CASE_ID,
        "claim_type": "extracted",
        "statement": f"gauge reads {value}",
        "subject": Subject(entity_id=ENTITY, link_status="resolved"),
        "attribute": "pressure",
        "value": value,
        "value_type": "numeric",
        "unit": unit,
        "unit_status": status,
        "temporal": Temporal(
            valid_time=Interval(
                start=DAY_START, end=DAY_END, granularity="day", resolved_from="explicit"
            ),
            observed_time=ObservedTime(at=DAY_END, basis="document_date"),
            timezone_original=CFG.case.plant_tz,
        ),
        "modality": "image",
        "evidence": TableCellPointer(
            source_id="src-photo",
            sha256=sha("photo"),
            row=0,
            column="x",
            raw_value=str(value),
            row_sha256=sha("r"),
            row_byte_offset=0,
        ),
        "derived_from": [],
        "method": Method(extractor="gauge", extractor_version="1", rule_id="gauge.read"),
        "confidence": Confidence(value=0.8, calibrated=False, components={}, stage="pre"),
    }
    return build_claim(**fields)


def _ctx() -> GateContext:
    envelope = Envelope(
        envelope_id="env_" + "0" * 24,
        machine=ENTITY,
        series_id=SERIES,
        scope=["pressure"],
        quiet_days=[],
        n=0,
        med={"pressure": 100.0},
        mad={"pressure": 5.0},
        T_star=3.0,
        pooled="none",
        pool_members=[],
        degenerate_channels=[],
        params=CFG.envelope,
        partition_hashes={SERIES: sha("partition")},
    )
    return GateContext(config=CFG, config_hash=config_hash(CFG), envelopes=[envelope])


def test_documented_conversion_is_exact() -> None:
    assert convert(Decimal("2.5"), "bar", "kPa") == Decimal("250.000000")
    assert convert(Decimal("212"), "degF", "degC") == Decimal("100.000000")
    assert convert(Decimal("7"), "kPa", "kPa") == Decimal("7")


def test_normalise_converts_bar_to_kpa_and_rehashes() -> None:
    (out,) = normalise_units([_gauge(2.5, "bar")], CFG)
    assert out.normalized_value == 250.0 and out.normalized_unit == "kPa"
    assert out.value == 2.5 and out.unit == "bar"  # the raw reading is kept
    assert verify_claim(out)


def test_unknown_unit_never_converts() -> None:
    unknown = _gauge(2.5, None, "unknown")
    assert normalise_units([unknown], CFG) == [unknown]
    undocumented = _gauge(2.5, "furlongs")
    assert normalise_units([undocumented], CFG) == [undocumented]


def test_sensor_native_is_never_converted() -> None:
    window = _window("pressure", {DAY_START: 100.0})
    (out,) = normalise_units([window], CFG)
    assert out is window and out.normalized_value is None


def test_gauge_vs_telemetry_cannot_compare() -> None:
    telemetry = _window("pressure", {DAY_START: 100.0})
    gauge = _gauge(2.5, "bar")
    for a, b in ((gauge, telemetry), (telemetry, gauge)):
        record = gate(a, b, _ctx())
        assert record.outcome == "cant_compare"
        assert record.reason == "They can't be compared: telemetry unit undocumented"
        assert [c.n for c in record.checks] == [1, 2, 3, 4]
        assert not record.checks[-1].passed
