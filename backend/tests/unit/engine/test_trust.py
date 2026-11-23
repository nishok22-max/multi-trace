"""B-09/B-10: confidence, holds, derived review status. Named: test_c17_confidence_computed,
test_undeclared_provenance_no_corroboration, test_low_confidence_claim_never_pairs,
test_held_claims_never_pair, prop_status_derived_monotone (simple form)."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.factories import (
    decision_event,
    make_decision,
    make_review_item,
    opened_event,
)
from tests.unit.engine.test_entities import _claim
from tests.unit.engine.test_gaps import CFG
from trace_adapters.fakes.clock import FixedClock
from trace_core.compare.pairs import candidate_pairs
from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord
from trace_core.models.records import ComparisonRecord, GateCheck, ReadingChoice
from trace_core.models.time import ObservedTime, Temporal, UnknownTime
from trace_core.review.holds import apply_holds
from trace_core.review.status import add_working_days, derive_review_status
from trace_core.score.confidence import score, score_pre
from trace_core.stage_types import Provenance


def _resolved(at: int = 0, source: str = "src-report") -> ClaimRecord:
    claim = _claim("M21", "resolved", "machine:21", at)
    fields = claim.model_dump(mode="python")
    fields["confidence"]["components"] = {"extractor": 0.95}
    pointer = fields["evidence"]
    pointer["source_id"] = source
    return build_claim(**fields)


def _undated(at: int = 0) -> ClaimRecord:
    fields = _resolved(at).model_dump(mode="python")
    fields["temporal"] = Temporal(
        valid_time=UnknownTime(reason="no date"),
        observed_time=ObservedTime(at=None, basis="document_date"),
        timezone_original=CFG.case.plant_tz,
    )
    return build_claim(**fields)


def _agree(a: ClaimRecord, b: ClaimRecord) -> ComparisonRecord:
    return ComparisonRecord(
        comparison_id="cmp_" + "0" * 24,
        claim_a=a.claim_id,
        claim_b=b.claim_id,
        config_hash="0" * 64,
        checks=[
            GateCheck.model_validate({"n": 1, "name": "same_entity", "pass": True, "detail": ""})
        ],
        outcome="agree",
        reason="x",
    )


def test_c17_confidence_computed() -> None:
    (out,) = score_pre([_resolved()], CFG)
    comps = out.confidence.components
    expected = 1.0
    for name in ("extractor", "entity_link", "time_precision", "unit_factor", "reliability_adj"):
        expected *= comps[name]
    assert out.confidence.value == expected and comps["corroboration"] == 0.0
    assert out.confidence.calibrated is False and out.confidence.stage == "pre"
    assert comps["extractor"] == CFG.gate.text_extractor_prior or comps["extractor"] == 0.95


def test_low_confidence_claim_never_pairs() -> None:
    good, bad = _resolved(0), _undated(40)
    scored = score_pre([good, bad], CFG)
    assert scored[1].confidence.value == 0.0  # no date, no confidence
    eligible, held = apply_holds(scored, [], [], [], CFG)
    assert [c.claim_id for c in held] == [scored[1].claim_id]
    assert list(candidate_pairs(eligible, {"operating_state": "operating_state"})) == []


def test_held_claims_never_pair() -> None:
    ambiguous = _claim("Zzzz", "ambiguous")
    eligible, held = apply_holds([ambiguous, _resolved(40)], [], [], [], CFG)
    assert [c.claim_id for c in held] == [ambiguous.claim_id]
    assert all(c.subject.link_status == "resolved" for c in eligible)


def test_open_item_holds_and_accepting_decision_releases() -> None:
    (claim,) = score_pre([_resolved()], CFG)
    item = make_review_item([claim.claim_id])
    _, held = apply_holds([claim], [item], [opened_event(item)], [], CFG)
    assert held == [claim]
    accept = make_decision(item, ReadingChoice(verdict="accept"))
    eligible, held = apply_holds([claim], [item], [], [accept], CFG)
    assert eligible == [claim] and held == []
    reject = make_decision(item, ReadingChoice(verdict="reject"))
    eligible, held = apply_holds([claim], [item], [], [reject], CFG)
    assert held == [claim] and eligible == []


def test_undeclared_provenance_no_corroboration() -> None:
    a, b = score_pre([_resolved(0, "src-a"), _resolved(40, "src-b")], CFG)
    comparisons = [_agree(a, b)]
    undeclared = score([a, b], comparisons, Provenance(), CFG)
    assert [c.confidence.value for c in undeclared] == [a.confidence.value, b.confidence.value]
    declared = score([a, b], comparisons, Provenance(derived_from={"src-a": [], "src-b": []}), CFG)
    boosted = a.confidence.value * (1 + CFG.gate.lambda_corroboration)
    assert declared[0].confidence.value == min(1.0, boosted)
    assert declared[0].confidence.components["corroboration"] == 1.0
    assert declared[0].confidence.stage == "final" and not declared[0].confidence.calibrated


def test_shared_ancestry_gives_no_credit() -> None:
    a, b = score_pre([_resolved(0, "src-a"), _resolved(40, "src-b")], CFG)
    derived = Provenance(derived_from={"src-a": [], "src-b": ["src-a"]})
    out = score([a, b], [_agree(a, b)], derived, CFG)
    assert out[0].confidence.components["corroboration"] == 0.0


def test_score_never_changes_holds() -> None:
    bad = score_pre([_undated()], CFG)
    final = score(bad, [], Provenance(), CFG)
    assert apply_holds(final, [], [], [], CFG)[1] == final


def test_status_open_decided_and_escalated() -> None:
    item = make_review_item(["clm_" + "0" * 24])  # opened 2015-03-15T09:10Z, a Sunday
    calendar = CFG.case.calendar
    assert datetime(2015, 3, 15, tzinfo=UTC).weekday() == 6
    early = FixedClock("2015-03-16T09:00:00Z")  # Monday: not yet a full working day
    assert derive_review_status([item], [opened_event(item)], early, calendar) == {
        item.review_id: "open"
    }
    late = FixedClock("2015-03-17T09:11:00Z")  # past one working day after Monday
    assert derive_review_status([item], [opened_event(item)], late, calendar) == {
        item.review_id: "escalated"
    }
    decision = make_decision(item, ReadingChoice(verdict="accept"))
    events = [opened_event(item), decision_event(decision, 1)]
    assert derive_review_status([item], events, late, calendar) == {item.review_id: "decided"}


def test_working_days_skip_weekend_and_holidays() -> None:
    cal = CFG.case.calendar
    friday = datetime(2015, 3, 13, tzinfo=UTC).date()
    assert add_working_days(friday, 1, cal).isoformat() == "2015-03-16"
    with_holiday = cal.model_copy(update={"holidays": ["2015-03-16"]})
    assert add_working_days(friday, 1, with_holiday).isoformat() == "2015-03-17"
