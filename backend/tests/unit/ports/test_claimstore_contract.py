"""ClaimStore contract, run against MemClaimStore and SqliteClaimStore."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.factories import (
    CASE_ID,
    decision_event,
    make_case,
    make_claim,
    make_decision,
    make_review_item,
    make_source,
    make_version,
    opened_event,
    sha,
)
from trace_adapters.fakes import MemClaimStore
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_core.errors import (
    AlreadyDecided,
    AppendOnlyViolation,
    EvidenceChanged,
    IntegrityError,
)
from trace_core.models.case import CaseVersion, VersionMembers, VersionRecords
from trace_core.models.records import (
    EntityChoice,
    EscalateChoice,
    ExplainChoice,
    ReadingChoice,
    ReviewItem,
)
from trace_core.ports import ClaimStore, Committed, Moved

Factory = Callable[[Path], ClaimStore]
FACTORIES: dict[str, Factory] = {
    "mem": lambda tmp: MemClaimStore(),
    "sqlite": lambda tmp: SqliteClaimStore(tmp / "trace.db"),
}


@pytest.fixture(params=list(FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ClaimStore:
    return FACTORIES[request.param](tmp_path)


class Seeded:
    """A store with a case, two claims, one review item and version 1."""

    def __init__(self, store: ClaimStore) -> None:
        self.store = store
        self.claims = [make_claim(0), make_claim(1)]
        self.item: ReviewItem = make_review_item([c.claim_id for c in self.claims])
        store.append(
            CASE_ID, [make_case(), make_source(), *self.claims, self.item, opened_event(self.item)]
        )
        records = VersionRecords(
            claims=self.claims,
            comparisons=[],
            conflicts=[],
            envelopes=[],
            review_items=[self.item],
            decisions=[],
        )
        self.v1 = make_version(1, None, records)
        store.put_version(self.v1, VersionMembers.from_records(records))

    def next_version(self, parent: CaseVersion) -> CaseVersion:
        return make_version(parent.version + 1, parent, parent.records)


@pytest.fixture
def seeded(store: ClaimStore) -> Seeded:
    return Seeded(store)


# --------------------------------------------------------------------------- basics
def test_empty_store(store: ClaimStore) -> None:
    assert store.latest(CASE_ID) is None
    assert store.get_version(CASE_ID, 1) is None
    assert store.load_claims(CASE_ID, 1) == []
    assert store.review_events(CASE_ID) == []


def test_append_is_idempotent(seeded: Seeded) -> None:
    seeded.store.append(CASE_ID, [make_case(), make_source(), *seeded.claims, seeded.item])
    assert len(seeded.store.load_claims(CASE_ID, 1)) == 2


def test_append_differing_content_is_rejected(seeded: Seeded) -> None:
    tampered = seeded.claims[0].model_copy(update={"record_hash": sha("tampered")})
    with pytest.raises(AppendOnlyViolation):
        seeded.store.append(CASE_ID, [tampered])
    with pytest.raises(AppendOnlyViolation):
        seeded.store.append(CASE_ID, [make_source(size=999)])


def test_append_is_all_or_nothing(seeded: Seeded) -> None:
    fresh = make_claim(7)
    tampered = seeded.claims[0].model_copy(update={"record_hash": sha("tampered")})
    with pytest.raises(AppendOnlyViolation):
        seeded.store.append(CASE_ID, [fresh, tampered])
    records = VersionRecords(
        claims=[fresh], comparisons=[], conflicts=[], envelopes=[], review_items=[], decisions=[]
    )
    with pytest.raises(IntegrityError):  # `fresh` was rolled back, so it is not a valid member
        seeded.store.put_version(
            make_version(2, seeded.v1, records), VersionMembers.from_records(records)
        )


def test_append_to_a_different_case_is_rejected(seeded: Seeded) -> None:
    with pytest.raises(ValueError):
        seeded.store.append("another-case", [make_claim(3)])


# ------------------------------------------------------------------------- versions
def test_version_round_trip_and_latest(seeded: Seeded) -> None:
    assert seeded.store.get_version(CASE_ID, 1) == seeded.v1
    assert seeded.store.latest(CASE_ID) == seeded.v1
    v2 = seeded.next_version(seeded.v1)
    seeded.store.put_version(v2, VersionMembers.from_records(v2.records))
    assert seeded.store.latest(CASE_ID) == v2
    assert seeded.store.get_version(CASE_ID, 1) == seeded.v1  # old versions are frozen


def test_version_chain_is_enforced(seeded: Seeded) -> None:
    members = VersionMembers.from_records(seeded.v1.records)
    with pytest.raises(IntegrityError):  # same version twice
        seeded.store.put_version(seeded.v1, members)
    with pytest.raises(IntegrityError):  # skipped a version
        seeded.store.put_version(make_version(3, seeded.v1, seeded.v1.records), members)
    broken = make_version(2, seeded.v1, seeded.v1.records).model_copy(
        update={"parent_manifest_hash": sha("not the parent")}
    )
    with pytest.raises(IntegrityError):  # does not chain to the latest manifest hash
        seeded.store.put_version(broken, members)


def test_version_members_must_exist(seeded: Seeded) -> None:
    ghost = VersionMembers(claim_ids=["clm_" + "f" * 24], comparison_ids=[], conflict_ids=[])
    with pytest.raises(IntegrityError):
        seeded.store.put_version(seeded.next_version(seeded.v1), ghost)
    assert seeded.store.latest(CASE_ID) == seeded.v1


def test_load_claims_sorted_by_valid_start_then_id_unknown_last(store: ClaimStore) -> None:
    def at(start: str, end: str) -> dict[str, object]:
        return {
            "valid_time": {
                "start": start,
                "end": end,
                "granularity": "hour",
                "resolved_from": "explicit",
            },
            "observed_time": {"at": None, "basis": "ingest_time"},
        }

    late = make_claim(1, temporal=at("2015-03-14T10:00:00Z", "2015-03-14T11:00:00Z"))
    early = make_claim(2, temporal=at("2015-03-14T01:00:00Z", "2015-03-14T02:00:00Z"))
    unknown = make_claim(
        3,
        temporal={
            "valid_time": {"granularity": "unknown", "reason": "no date"},
            "observed_time": {"at": None, "basis": "ingest_time"},
        },
    )
    store.append(CASE_ID, [make_case(), make_source(), late, unknown, early])
    records = VersionRecords(
        claims=[late, unknown, early],
        comparisons=[],
        conflicts=[],
        envelopes=[],
        review_items=[],
        decisions=[],
    )
    store.put_version(make_version(1, None, records), VersionMembers.from_records(records))
    assert [c.claim_id for c in store.load_claims(CASE_ID, 1)] == [
        early.claim_id,
        late.claim_id,
        unknown.claim_id,
    ]


def test_review_events_are_ordered_by_seq(seeded: Seeded) -> None:
    decision = make_decision(seeded.item)
    seeded.store.commit_decision(
        CASE_ID, 1, decision, decision_event(decision, 1), seeded.next_version(seeded.v1)
    )
    events = seeded.store.review_events(CASE_ID, seeded.item.review_id)
    assert [(e.seq, e.kind) for e in events] == [(0, "opened"), (1, "decided")]
    assert seeded.store.review_events(CASE_ID, "rv_" + "0" * 24) == []


# ------------------------------------------------------------------------ decisions
def test_commit_decision_happy_path(seeded: Seeded) -> None:
    decision = make_decision(seeded.item)
    v2 = seeded.next_version(seeded.v1)
    result = seeded.store.commit_decision(CASE_ID, 1, decision, decision_event(decision, 1), v2)
    assert result == Committed(version=2, manifest_hash=v2.manifest_hash)
    assert seeded.store.latest(CASE_ID) == v2


def test_commit_decision_moved_writes_nothing(seeded: Seeded) -> None:
    decision = make_decision(seeded.item)
    result = seeded.store.commit_decision(
        CASE_ID, 0, decision, decision_event(decision, 1), seeded.next_version(seeded.v1)
    )
    assert result == Moved(latest=1)
    assert seeded.store.latest(CASE_ID) == seeded.v1
    assert len(seeded.store.review_events(CASE_ID)) == 1  # only the opened event


def test_already_decided_returns_the_existing_decision(seeded: Seeded) -> None:
    first = make_decision(seeded.item)
    v2 = seeded.next_version(seeded.v1)
    seeded.store.commit_decision(CASE_ID, 1, first, decision_event(first, 1), v2)
    second = make_decision(
        seeded.item, ReadingChoice(verdict="accept"), base_version=2, sub="reviewer2"
    )
    with pytest.raises(AlreadyDecided) as info:
        seeded.store.commit_decision(
            CASE_ID, 2, second, decision_event(second, 2), seeded.next_version(v2)
        )
    assert info.value.existing_decision_id == first.decision_id
    assert seeded.store.latest(CASE_ID) == v2


def test_supersede_bypasses_already_decided(seeded: Seeded) -> None:
    first = make_decision(seeded.item)
    v2 = seeded.next_version(seeded.v1)
    seeded.store.commit_decision(CASE_ID, 1, first, decision_event(first, 1), v2)
    senior = make_decision(
        seeded.item,
        EntityChoice(entity_id="machine:21"),
        base_version=2,
        sub="senior1",
        supersedes=first.decision_id,
    )
    out = seeded.store.commit_decision(
        CASE_ID, 2, senior, decision_event(senior, 2), seeded.next_version(v2)
    )
    assert isinstance(out, Committed) and out.version == 3


def test_evidence_changed_is_rejected_and_nothing_is_written(seeded: Seeded) -> None:
    decision = make_decision(seeded.item, evidence_hash=sha("stale evidence"))
    with pytest.raises(EvidenceChanged):
        seeded.store.commit_decision(
            CASE_ID, 1, decision, decision_event(decision, 1), seeded.next_version(seeded.v1)
        )
    assert seeded.store.latest(CASE_ID) == seeded.v1
    assert len(seeded.store.review_events(CASE_ID)) == 1


def test_escalation_does_not_close_the_item(seeded: Seeded) -> None:
    escalate = make_decision(seeded.item, EscalateChoice(), sub="reviewer1")
    v2 = seeded.next_version(seeded.v1)
    seeded.store.commit_decision(CASE_ID, 1, escalate, decision_event(escalate, 1), v2)
    resolve = make_decision(seeded.item, base_version=2, sub="senior1")
    out = seeded.store.commit_decision(
        CASE_ID, 2, resolve, decision_event(resolve, 2), seeded.next_version(v2)
    )
    assert isinstance(out, Committed)


def test_explain_event_kind_and_double_explain(store: ClaimStore) -> None:
    claims = [make_claim(0), make_claim(1)]
    item = make_review_item([c.claim_id for c in claims], review_type="conflict_explain")
    store.append(CASE_ID, [make_case(), make_source(), *claims, item, opened_event(item)])
    records = VersionRecords(
        claims=claims, comparisons=[], conflicts=[], envelopes=[], review_items=[item], decisions=[]
    )
    v1 = make_version(1, None, records)
    store.put_version(v1, VersionMembers.from_records(records))
    explain = make_decision(item, ExplainChoice(explanation="planned maintenance window"))
    event = decision_event(explain, 1)
    assert event.kind == "explained"
    v2 = make_version(2, v1, records)
    assert isinstance(store.commit_decision(CASE_ID, 1, explain, event, v2), Committed)
    again = make_decision(
        item, ExplainChoice(explanation="second note"), base_version=2, sub="reviewer2"
    )
    with pytest.raises(AlreadyDecided):
        store.commit_decision(
            CASE_ID, 2, again, decision_event(again, 2), make_version(3, v2, records)
        )


def test_event_must_match_decision_and_sequence(seeded: Seeded) -> None:
    decision = make_decision(seeded.item)
    v2 = seeded.next_version(seeded.v1)
    with pytest.raises(ValueError):  # wrong seq
        seeded.store.commit_decision(CASE_ID, 1, decision, decision_event(decision, 5), v2)
    other = make_decision(seeded.item, ReadingChoice(verdict="reject"), sub="x")
    with pytest.raises(ValueError):  # event belongs to a different decision
        seeded.store.commit_decision(CASE_ID, 1, decision, decision_event(other, 1), v2)
    assert seeded.store.latest(CASE_ID) == seeded.v1
