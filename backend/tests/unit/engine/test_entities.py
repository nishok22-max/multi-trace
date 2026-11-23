"""B-06: entity resolution. Named: test_transposed_digits_never_autolink,
test_serial_conflict_vetoes, test_decision_keyed_by_mention_key."""

from __future__ import annotations

from tests.factories import CASE_ID, sha
from tests.unit.engine.test_gaps import CFG, DAY_END, DAY_START
from trace_core.ids import build_claim, review_id
from trace_core.models.claims import ClaimRecord, Confidence, MentionKey, Method, Subject
from trace_core.models.config import AliasEntry, ConfigBundle
from trace_core.models.evidence import TableCellPointer
from trace_core.models.time import Interval, ObservedTime, Temporal
from trace_core.normalise.entities import resolve_entities

OPENED = "2015-08-06T04:00:00Z"
SRC = sha("report")

CONFIG: ConfigBundle = CFG.model_copy(
    update={
        "aliases": [
            AliasEntry(
                entity_id="machine:21",
                canonical_name="Machine 21",
                aliases=["M21", "M-21", "SN-0021"],
            ),
            AliasEntry(
                entity_id="machine:12",
                canonical_name="Machine 12",
                aliases=["M12", "M-12", "SN-0012"],
            ),
        ]
    }
)


def _claim(mention: str | None, status: str, entity: str | None = None, at: int = 0) -> ClaimRecord:
    key = MentionKey(source_sha256=SRC, locator=f"p1:{at}-{at + 5}") if mention else None
    return build_claim(
        case_id=CASE_ID,
        claim_type="extracted",
        statement=f"{mention} ran normally",
        subject=Subject(mention=mention, entity_id=entity, link_status=status, mention_key=key),
        attribute="operating_state",
        value="normal",
        value_type="categorical",
        unit=None,
        unit_status="not_applicable",
        temporal=Temporal(
            valid_time=Interval(
                start=DAY_START, end=DAY_END, granularity="day", resolved_from="explicit"
            ),
            observed_time=ObservedTime(at=DAY_END, basis="document_date"),
            timezone_original=CFG.case.plant_tz,
        ),
        modality="text",
        evidence=TableCellPointer(
            source_id="src-report",
            sha256=SRC,
            row=at,
            column="x",
            raw_value="x",
            row_sha256=sha("row"),
            row_byte_offset=at,
        ),
        derived_from=[],
        method=Method(extractor="rules:phrase_list", extractor_version="1", rule_id="phrase.x"),
        confidence=Confidence(value=0.95, calibrated=False, components={}, stage="pre"),
    )


def _resolve(claims: list[ClaimRecord]):
    return resolve_entities(claims, CONFIG, opened_at=OPENED)


def test_transposed_digits_never_autolink() -> None:
    out, items = _resolve(
        [_claim("M-21", "unresolved"), _claim("M12", "resolved", "machine:12", 40)]
    )
    claim = out[0]
    assert claim.subject.link_status == "ambiguous" and claim.subject.entity_id is None
    by_entity = {c.entity_id: c for c in claim.subject.candidates}
    assert by_entity["machine:21"].score == 1.0  # exact alias, but 21 is not what the doc links
    assert not by_entity["machine:21"].vetoed
    # "Press 21" style: the transposed machine 12 is shown as a vetoed candidate with a reason
    transposed = by_entity["machine:12"]
    assert transposed.vetoed
    assert any("digit_transposition" in r for r in transposed.reasons)
    assert [i.type for i in items] == ["ambiguous_entity"]


def test_exact_alias_needs_a_non_string_feature_to_autolink() -> None:
    (alone, *_), items = _resolve([_claim("m 21", "unresolved")])
    assert alone.subject.link_status == "ambiguous"  # string match alone is never enough
    assert len(items) == 1
    out, items = _resolve(
        [_claim("m 21", "unresolved"), _claim("M21", "resolved", "machine:21", 40)]
    )
    assert out[0].subject.link_status == "resolved" and out[0].subject.entity_id == "machine:21"
    assert items == []  # the document context agrees


def test_serial_conflict_vetoes() -> None:
    out, _ = _resolve(
        [_claim("SN-0012", "unresolved"), _claim("M21", "resolved", "machine:21", 40)]
    )
    by_entity = {c.entity_id: c for c in out[0].subject.candidates}
    assert by_entity["machine:12"].features["serial"] == 1.0
    assert by_entity["machine:21"].vetoed  # a different serial number rules machine 21 out
    assert out[0].subject.link_status == "resolved"
    assert out[0].subject.entity_id == "machine:12"  # serial agreement is a non-string feature


def test_decision_keyed_by_mention_key() -> None:
    first, items = _resolve([_claim("M-21", "unresolved")])
    again, items_again = _resolve([_claim("M-21", "unresolved")])
    key = first[0].subject.mention_key
    assert key is not None
    assert items[0].review_id == review_id("ambiguous_entity", [key])
    assert items[0].review_id == items_again[0].review_id
    assert items[0].mention_keys == [key]
    assert len(items[0].candidates or []) <= 3


def test_unmatched_mention_stays_unresolved_without_review_item() -> None:
    out, items = _resolve([_claim("Zzzz", "unresolved")])
    assert out[0].subject.entity_id is None
    assert out[0].subject.link_status in ("ambiguous", "unresolved")
