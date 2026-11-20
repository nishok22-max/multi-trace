"""B-01 model tests: validators, ID rules, forbidden fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.factories import CASE_ID, claim_fields, make_claim, sha
from trace_core.ids import build_claim, review_id, verify_claim
from trace_core.models.api_io import DecisionRequest, choice_allowed
from trace_core.models.claims import ClaimRecord, MentionKey
from trace_core.models.records import ConflictRecord, EntityChoice, EscalateChoice, ReadingChoice
from trace_core.models.time import Interval, ObservedTime, Temporal, UnknownTime


def test_unknown_time_has_no_bounds() -> None:
    assert "start" not in UnknownTime.model_fields
    assert "end" not in UnknownTime.model_fields
    with pytest.raises(ValidationError):
        UnknownTime(reason="no document date", start="2015-03-14T00:00:00Z")  # type: ignore[call-arg]
    temporal = Temporal(
        valid_time=UnknownTime(reason="no document date"),
        observed_time=ObservedTime(basis="ingest_time"),
    )
    assert temporal.valid_time.granularity == "unknown"


def test_observed_time_never_file_timestamp() -> None:
    with pytest.raises(ValidationError):
        ObservedTime(basis="file_timestamp")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        "2015-03-14",
        "2015-03-14T00:00:00",
        "2015-03-14T00:00Z",
        "2015-02-30T00:00:00Z",
        "2015-03-14T24:00:00Z",
        "2015-03-14T00:00:00+05:30",
    ],
)
def test_utc_str_is_fixed_width(bad: str) -> None:
    with pytest.raises(ValidationError):
        Interval(start=bad, end="2016-01-01T00:00:00Z", granularity="day", resolved_from="x")


def test_interval_is_half_open_and_ordered() -> None:
    with pytest.raises(ValidationError):
        Interval(
            start="2015-03-14T00:00:00Z",
            end="2015-03-14T00:00:00Z",
            granularity="day",
            resolved_from="explicit",
        )


def test_inferred_claim_without_derived_from_rejected() -> None:
    with pytest.raises(ValidationError, match="derived_from"):
        make_claim(claim_type="inferred", evidence=None, derived_from=[])


def test_inferred_claim_without_rule_id_rejected() -> None:
    with pytest.raises(ValidationError, match="rule_id"):
        make_claim(
            claim_type="inferred",
            evidence=None,
            derived_from=["clm_" + "a" * 24],
            method={"extractor": "envelope_check", "extractor_version": "1.0.0"},
        )


def test_inferred_claim_with_parents_and_rule_is_valid() -> None:
    claim = make_claim(
        claim_type="inferred",
        evidence=None,
        derived_from=["clm_" + "a" * 24],
        method={"extractor": "envelope_check", "extractor_version": "1.0.0", "rule_id": "r1"},
    )
    assert claim.claim_type == "inferred"


def test_extracted_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        make_claim(evidence=None)


def test_sensor_native_with_normalized_value_rejected() -> None:
    with pytest.raises(ValidationError, match="sensor_native"):
        make_claim(unit_status="sensor_native", normalized_value=1.5)
    with pytest.raises(ValidationError, match="sensor_native"):
        make_claim(unit_status="sensor_native", normalized_unit="kPa")
    assert make_claim(unit_status="sensor_native").normalized_value is None


def test_claims_have_no_version_and_no_status() -> None:
    assert "version" not in ClaimRecord.model_fields
    assert "status" not in ClaimRecord.model_fields
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**make_claim().model_dump(), "status": "open"})
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**make_claim().model_dump(), "version": 7})


def test_conflict_is_never_averaged_and_has_no_status() -> None:
    assert "status" not in ConflictRecord.model_fields
    base = {
        "conflict_id": "cf_" + "a" * 24,
        "comparison_ids": ["cmp_" + "b" * 24],
        "sides": ["clm_" + "c" * 24, "clm_" + "d" * 24],
        "magnitude": {"statistic": "robust_max_z", "unit": "unitless"},
    }
    assert ConflictRecord.model_validate(base).averaged is False
    with pytest.raises(ValidationError):
        ConflictRecord.model_validate({**base, "averaged": True})


def _decision_body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "choice": {"type": "entity", "entity_id": "machine:21"},
        "reason": "serial SN-0021 matches the register",
        "base_version": 3,
        "shown_evidence_hash": sha("evidence"),
    }
    return {**body, **over}


def test_decision_request_with_reviewer_field_rejected() -> None:
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(_decision_body(reviewer="mallory"))
    assert DecisionRequest.model_validate(_decision_body()).base_version == 3


@pytest.mark.parametrize("reason", ["", "too short", "x" * 14])
def test_decision_reason_under_15_chars_rejected(reason: str) -> None:
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(_decision_body(reason=reason))
    assert DecisionRequest.model_validate(_decision_body(reason="x" * 15)).reason == "x" * 15


def test_decision_choice_is_a_discriminated_union() -> None:
    req = DecisionRequest.model_validate(_decision_body(choice={"type": "escalate"}))
    assert isinstance(req.choice, EscalateChoice)
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(_decision_body(choice={"type": "bogus"}))
    with pytest.raises(ValidationError):  # fields of another choice type are not accepted
        DecisionRequest.model_validate(
            _decision_body(choice={"type": "escalate", "entity_id": "machine:21"})
        )


def test_choice_is_validated_against_the_item_type() -> None:
    assert choice_allowed("ambiguous_entity", EntityChoice(entity_id="machine:21"))
    assert not choice_allowed("hidden_text", EntityChoice(entity_id="machine:21"))
    assert choice_allowed("hidden_text", ReadingChoice(verdict="accept"))
    assert not choice_allowed("ambiguous_entity", ReadingChoice(verdict="reject"))
    assert choice_allowed("hidden_text", EscalateChoice())


def test_id_formats_are_regex_constrained() -> None:
    claim = make_claim()
    assert claim.claim_id.startswith("clm_") and len(claim.claim_id) == 28
    assert verify_claim(claim)
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**claim.model_dump(), "claim_id": "clm_XYZ"})
    with pytest.raises(ValidationError):
        ClaimRecord.model_validate({**claim.model_dump(), "case_id": "../etc/passwd"})


def test_review_id_stable_across_extractor_version() -> None:
    keys = [MentionKey(source_sha256=sha("s"), locator="p1:3")]
    a = make_claim(method={"extractor": "rules", "extractor_version": "1.0.0", "rule_id": "r"})
    b = make_claim(method={"extractor": "rules", "extractor_version": "2.0.0", "rule_id": "r"})
    assert a.claim_id != b.claim_id  # claim ids DO change with the extractor version
    assert review_id("ambiguous_entity", keys) == review_id("ambiguous_entity", list(keys))
    # review ids depend only on (type, sorted mention keys): order and claims are irrelevant
    k1 = MentionKey(source_sha256=sha("a"), locator="1")
    k2 = MentionKey(source_sha256=sha("b"), locator="2")
    assert review_id("hidden_text", [k1, k2]) == review_id("hidden_text", [k2, k1])
    assert review_id("hidden_text", [k1]) != review_id("ambiguous_entity", [k1])


def test_review_id_needs_a_mention_key() -> None:
    from trace_core.errors import CanonicalizationError

    with pytest.raises(CanonicalizationError):
        review_id("hidden_text", [])


def test_claim_id_ignores_presentation_and_wall_clock() -> None:
    base = make_claim()
    other = build_claim(
        **claim_fields(
            0,
            label="Z-9",
            statement="different words",
            created_at="2030-01-01T00:00:00Z",
            confidence={"value": 0.9, "calibrated": True},
        )
    )
    assert base.claim_id == other.claim_id
    assert base.record_hash != other.record_hash  # the body differs, so the record hash does
    assert make_claim(value="abnormal").claim_id != base.claim_id
    assert CASE_ID == base.case_id
