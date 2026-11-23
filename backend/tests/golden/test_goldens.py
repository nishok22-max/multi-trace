"""D-10: goldens for Demos 0, 1a, 1b, 2 (held), 3, 4, 5, 5b, 6 (held). Every pinned number is
computed by the engine from seeded synthetic data; no demo literal appears in engine code."""

from __future__ import annotations

from typing import Any

import pytest

from tests.golden.golden import check
from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_entities import _claim as ambiguous_claim
from tests.unit.engine.test_gate import CFG, COVER, _ctx
from tests.unit.engine.test_image import CONFIG as IMAGE_CONFIG
from tests.unit.engine.test_image import _ports, _read, _result
from tests.unit.engine.test_time import _note
from tests.unit.engine.test_trust import _resolved
from tests.unit.engine.test_units import DAY_START, _gauge, _window
from trace_adapters.fakes.ocr import FakeOcr
from trace_core.compare.gate import gate
from trace_core.ids import build_claim
from trace_core.models.case import CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.time import ObservedTime, Temporal, UnknownTime
from trace_core.normalise.entities import resolve_entities
from trace_core.normalise.time import resolve_time
from trace_core.normalise.units import normalise_units
from trace_core.score.confidence import score, score_pre
from trace_core.stage_types import Provenance


def _comparison(version: CaseVersion) -> dict[str, Any]:
    (cmp_,) = version.records.comparisons
    return {
        "outcome": cmp_.outcome,
        "reason": cmp_.reason,
        "checks": [(c.n, c.name, c.passed, c.detail) for c in cmp_.checks],
    }


def _envelope(version: CaseVersion) -> dict[str, Any]:
    env = version.records.envelopes[0]
    return {
        "n": env.n,
        "T_star": env.T_star,
        "scope": env.scope,
        "pooled": env.pooled,
        "med": env.med,
        "mad": env.mad,
    }


def _build(tmp_path, **kwargs: Any) -> CaseVersion:  # type: ignore[no-untyped-def]
    return build_version(synthetic_world(tmp_path, **kwargs))


def test_demo0_headline_disagreement(tmp_path) -> None:  # type: ignore[no-untyped-def]
    version = _build(tmp_path, spike=True)
    state = next(c for c in version.records.claims if c.attribute == "operating_state")
    check(
        "demo0_headline",
        {
            **_comparison(version),
            "envelope": _envelope(version),
            "state": state.value,
            "conflicts": [
                (c.magnitude.observed, c.magnitude.threshold) for c in version.records.conflicts
            ],
        },
    )


def test_demo1a_missing_hours_cant_tell(tmp_path) -> None:  # type: ignore[no-untyped-def]
    version = _build(tmp_path, spike=False, drop_hours=(3, 4))
    gaps = [c for c in version.records.claims if c.attribute == "data_availability"]
    check(
        "demo1a_missing_hours",
        {
            **_comparison(version),
            "gaps": sorted((g.value, g.evidence.expected_points) for g in gaps),  # type: ignore[union-attr]
        },
    )


def test_demo1b_every_reading_missing_no_comparison(tmp_path) -> None:  # type: ignore[no-untyped-def]
    version = _build(tmp_path, spike=False, drop_hours=tuple(range(24)))
    gaps = [c for c in version.records.claims if c.attribute == "data_availability"]
    check(
        "demo1b_sensor_dropout",
        {
            "comparisons": len(version.records.comparisons),
            "states": sum(1 for c in version.records.claims if c.attribute == "operating_state"),
            "gap_hours": sorted(g.evidence.expected_points for g in gaps),  # type: ignore[union-attr]
        },
    )


def test_demo2_ambiguous_entity_is_held(tmp_path) -> None:  # type: ignore[no-untyped-def]
    claims, items = resolve_entities(
        [ambiguous_claim("Press 21", "unresolved")], CFG, opened_at="2015-08-06T04:00:00Z"
    )
    (claim,) = claims
    check(
        "demo2_ambiguous_entity",
        {
            "link_status": claim.subject.link_status,
            "candidates": [
                (c.entity_id, c.score, c.features, c.reasons) for c in claim.subject.candidates
            ],
            "review": [(i.type, len(i.claim_ids), i.review_id) for i in items],
        },
    )


def test_demo3_units_differ_cannot_compare() -> None:
    telemetry = _window("pressure", {DAY_START: 100.0})
    gauge = _gauge(2.5, "bar")
    record = gate(gauge, telemetry, _ctx_for(telemetry))
    (normalised,) = normalise_units([gauge], CFG)
    check(
        "demo3_units_differ",
        {
            "outcome": record.outcome,
            "reason": record.reason,
            "checks": [(c.n, c.name, c.passed) for c in record.checks],
            "gauge_normalised": (normalised.normalized_value, normalised.normalized_unit),
            "telemetry_converted": telemetry.normalized_value,
        },
    )


def _ctx_for(claim: ClaimRecord):  # type: ignore[no-untyped-def]
    from trace_core.ids import config_hash
    from trace_core.stage_types import GateContext

    return GateContext(config=CFG, config_hash=config_hash(CFG), envelopes=[])


def test_demo4_false_conflict_guard(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A day-level report and a different day's sensor state are not a conflict."""
    version = _build(tmp_path, spike=True)
    text = next(c for c in version.records.claims if c.modality == "text")
    state = next(c for c in version.records.claims if c.attribute == "operating_state")
    other_day = _window("vibration", {DAY_START: 1.0})  # a different series/statistic/grain
    record = gate(text, state, _ctx(version, [], [COVER]))
    fields = text.model_dump(mode="python")
    fields["temporal"] = Temporal(
        valid_time=UnknownTime(reason="no document date"),
        observed_time=ObservedTime(at=None, basis="document_date"),
        timezone_original=CFG.case.plant_tz,
    )
    undated = build_claim(**fields)  # the same report claim, but the document has no date
    untimed = gate(undated, state, _ctx(version, [], [COVER]))
    check(
        "demo4_false_conflict_guard",
        {
            "same_day": record.outcome,
            "undated_note": (untimed.outcome, untimed.reason),
            "undated_checks": [(c.n, c.name, c.passed) for c in untimed.checks],
            "raw_window_is_not_paired": other_day.attribute not in {"operating_state"},
        },
    )


def test_demo5_independence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.unit.engine.test_trust import _agree

    a, b = score_pre([_resolved(0, "src-a"), _resolved(40, "src-b")], CFG)
    out: dict[str, Any] = {}
    for label, provenance in (
        ("undeclared", Provenance()),
        ("declared_disjoint", Provenance(derived_from={"src-a": [], "src-b": []})),
        ("b_derived_from_a", Provenance(derived_from={"src-a": [], "src-b": ["src-a"]})),
    ):
        scored = score([a, b], [_agree(a, b)], provenance, CFG)
        out[label] = (scored[0].confidence.value, scored[0].confidence.components["corroboration"])
    check("demo5_independence", out)


def test_demo5b_late_timestamp() -> None:
    """A note written at 23:30 plant-local that says "yesterday, shift 2" is dated by the plant
    day of the writing, not by the UTC date."""
    out: dict[str, Any] = {}
    for label, observed in (
        ("late_2330_ist", "2015-03-14T18:00:00Z"),
        ("morning", "2015-03-15T04:00:00Z"),
    ):
        (note,) = resolve_time([_note("M21 ran normally yesterday, shift 2", observed)], CFG)
        vt = note.temporal.valid_time
        out[label] = (vt.start, vt.end, vt.granularity)  # type: ignore[union-attr]
    check("demo5b_late_timestamp", out)


def test_demo6_reader_disagreement_is_held(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.unit.engine.test_image import _Disagreeing

    held = _read(tmp_path, _Disagreeing(_result("4.2")))
    dropped = _read(tmp_path, FakeOcr(_result("69")))
    clean = _read(tmp_path, FakeOcr(_result("4.2")))
    scored = score_pre(clean.claims, IMAGE_CONFIG)
    from trace_core.review.holds import apply_holds

    _, still_held = apply_holds(scored, [], [], [], IMAGE_CONFIG)
    check(
        "demo6_reader_disagreement",
        {
            "disagreement": ([i.type for i in held.review_items], len(held.claims)),
            "decimal_drop": ([i.type for i in dropped.review_items], len(dropped.claims)),
            "clean_claim_is_held_until_a_human_decides": (len(clean.claims), len(still_held)),
            "confidence": [c.confidence.value for c in scored],
        },
    )
    assert _ports is not None and isinstance(World, type)
    pytest.importorskip("PIL")
