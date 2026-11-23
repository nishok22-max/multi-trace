"""B-07: time resolution. Named: test_local_day_boundary_2330, test_undated_note_time_unknown,
test_relative_time_yesterday_shift2 (test_client_timestamp_ignored is an API test, M4)."""

from __future__ import annotations

from tests.factories import CASE_ID, sha
from tests.unit.engine.test_gaps import CFG
from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord, Confidence, Method, Subject
from trace_core.models.evidence import TableCellPointer
from trace_core.models.time import Interval, ObservedTime, Temporal, UnknownTime
from trace_core.normalise.time import local_date, resolve_time

TZ = CFG.case.plant_tz


def _note(statement: str, observed_at: str | None) -> ClaimRecord:
    return build_claim(
        case_id=CASE_ID,
        claim_type="extracted",
        statement=statement,
        subject=Subject(entity_id="machine:21", link_status="resolved", mention="M21"),
        attribute="operating_state",
        value="normal",
        value_type="categorical",
        unit=None,
        unit_status="not_applicable",
        temporal=Temporal(
            valid_time=UnknownTime(reason="no date"),
            observed_time=ObservedTime(at=observed_at, basis="document_date"),
            timezone_original=TZ,
        ),
        modality="text",
        evidence=TableCellPointer(
            source_id="src-note",
            sha256=sha("note"),
            row=0,
            column="x",
            raw_value="x",
            row_sha256=sha("r"),
            row_byte_offset=0,
        ),
        derived_from=[],
        method=Method(extractor="rules:phrase_list", extractor_version="1", rule_id="phrase.x"),
        confidence=Confidence(value=0.95, calibrated=False, components={}, stage="pre"),
    )


def test_local_day_boundary_2330() -> None:
    """A note written 23:30 plant-local (18:00Z) is still dated that local day, not the UTC day."""
    observed = "2015-03-14T18:00:00Z"  # 23:30 IST on 14 March
    (out,) = resolve_time([_note("M21 ran normally today", observed)], CFG)
    vt = out.temporal.valid_time
    assert isinstance(vt, Interval) and vt.granularity == "day" and vt.resolved_from == "relative"
    assert local_date(vt.start, TZ).isoformat() == "2015-03-14"
    assert (vt.start, vt.end) == ("2015-03-13T18:30:00Z", "2015-03-14T18:30:00Z")


def test_undated_note_time_unknown() -> None:
    note = _note("M21 ran normally yesterday", None)
    assert resolve_time([note], CFG) == [note]  # no document date: stays unknown
    assert isinstance(note.temporal.valid_time, UnknownTime)


def test_relative_time_yesterday_shift2() -> None:
    observed = "2015-03-15T04:00:00Z"  # 09:30 IST on 15 March
    (out,) = resolve_time([_note("M21 ran normally yesterday, shift 2", observed)], CFG)
    vt = out.temporal.valid_time
    assert isinstance(vt, Interval) and vt.granularity == "shift"
    # shift_2 is 12:00-24:00 plant-local on 14 March
    assert (vt.start, vt.end) == ("2015-03-14T06:30:00Z", "2015-03-14T18:30:00Z")


def test_ambiguous_or_missing_relative_word_is_left_alone() -> None:
    both = _note("yesterday and today it ran normally", "2015-03-15T04:00:00Z")
    none = _note("it ran normally", "2015-03-15T04:00:00Z")
    assert resolve_time([both, none], CFG) == [both, none]


def test_dated_claims_are_untouched() -> None:
    dated = _note("ran normally yesterday", "2015-03-15T04:00:00Z")
    fields = dated.model_dump(mode="python")
    fields["temporal"] = Temporal(
        valid_time=Interval(
            start="2015-03-13T18:30:00Z",
            end="2015-03-14T18:30:00Z",
            granularity="day",
            resolved_from="explicit",
        ),
        observed_time=dated.temporal.observed_time,
        timezone_original=TZ,
    )
    explicit = build_claim(**fields)
    assert resolve_time([explicit], CFG) == [explicit]
