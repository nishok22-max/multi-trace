"""B-10: rerun_after_decision. Named: test_replay_identical_with_different_clock (engine part),
test_explain_never_changes_outcome, plus entity/reading decisions end to end."""

from __future__ import annotations

import pytest

from tests.factories import make_decision
from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_gate import CFG
from trace_adapters.fakes.clock import FixedClock
from trace_core.ids import build_claim, review_id
from trace_core.models.case import CaseVersion, VersionRecords
from trace_core.models.claims import Candidate, ClaimRecord, MentionKey, Subject
from trace_core.models.records import EntityChoice, ExplainChoice, ReadingChoice, ReviewItem
from trace_core.rerun import rerun_after_decision

KEY = MentionKey(source_sha256="a" * 64, locator="p1:10-18")


@pytest.fixture(scope="module")
def parent(tmp_path_factory: pytest.TempPathFactory) -> tuple[CaseVersion, ReviewItem, ClaimRecord]:
    world: World = synthetic_world(tmp_path_factory.mktemp("rerun"), spike=False)
    version = build_version(world)
    text = next(c for c in version.records.claims if c.modality == "text")
    fields = text.model_dump(mode="python")
    fields["subject"] = Subject(
        mention="Press 21",
        entity_id=None,
        link_status="ambiguous",
        candidates=[Candidate(entity_id="machine:21", score=0.6)],
        mention_key=KEY,
    )
    fields["supersedes"] = None
    ambiguous = build_claim(**fields)
    item = ReviewItem(
        review_id=review_id("ambiguous_entity", [KEY]),
        type="ambiguous_entity",
        claim_ids=[ambiguous.claim_id],
        mention_keys=[KEY],
        candidates=[Candidate(entity_id="machine:21", score=0.6)],
        evidence_hash="b" * 64,
        opened_at="2015-08-06T04:00:00Z",
    )
    claims = [c for c in version.records.claims if c.claim_id != text.claim_id] + [ambiguous]
    records = VersionRecords(
        claims=claims,
        comparisons=[],
        conflicts=[],
        envelopes=version.records.envelopes,
        review_items=[item],
        decisions=[],
    )
    return version.model_copy(update={"records": records}), item, ambiguous


def test_entity_decision_relinks_and_pairs(
    parent: tuple[CaseVersion, ReviewItem, ClaimRecord],
) -> None:
    base, item, ambiguous = parent
    decision = make_decision(item, EntityChoice(entity_id="machine:21"))
    child = rerun_after_decision(base, [decision], CFG, FixedClock("2015-08-06T05:00:00Z"))
    assert child.version == base.version + 1 and child.parent_manifest_hash == base.manifest_hash
    relinked = next(c for c in child.records.claims if c.supersedes == ambiguous.claim_id)
    assert relinked.subject.entity_id == "machine:21" and relinked.subject.link_status == "resolved"
    assert ambiguous.claim_id not in {c.claim_id for c in child.records.claims}
    assert child.records.review_items == base.records.review_items  # append-only evidence
    assert [d.decision_id for d in child.records.decisions] == [decision.decision_id]
    assert [c.outcome for c in child.records.comparisons] == ["agree"]


def test_unresolved_claim_never_pairs_before_a_decision(
    parent: tuple[CaseVersion, ReviewItem, ClaimRecord],
) -> None:
    base, _, _ = parent
    child = rerun_after_decision(base, [], CFG, FixedClock("2015-08-06T05:00:00Z"))
    assert child.records.comparisons == []  # held: the entity is a human decision


def test_reject_keeps_the_claim_held(parent: tuple[CaseVersion, ReviewItem, ClaimRecord]) -> None:
    base, item, _ = parent
    reject = make_decision(item, ReadingChoice(verdict="reject"))
    child = rerun_after_decision(base, [reject], CFG, FixedClock("2015-08-06T05:00:00Z"))
    assert child.records.comparisons == []


def test_explain_never_changes_outcome(parent: tuple[CaseVersion, ReviewItem, ClaimRecord]) -> None:
    base, item, _ = parent
    explain = make_decision(item, ExplainChoice(explanation="maintenance window"))
    plain = rerun_after_decision(base, [], CFG, FixedClock("2015-08-06T05:00:00Z"))
    explained = rerun_after_decision(base, [explain], CFG, FixedClock("2015-08-06T05:00:00Z"))
    assert explained.records.comparisons == plain.records.comparisons
    assert [c.claim_id for c in explained.records.claims] == [
        c.claim_id for c in plain.records.claims
    ]


def test_replay_identical_with_different_clock(
    parent: tuple[CaseVersion, ReviewItem, ClaimRecord],
) -> None:
    base, item, _ = parent
    decision = make_decision(item, EntityChoice(entity_id="machine:21"))
    one = rerun_after_decision(base, [decision], CFG, FixedClock("2015-08-06T05:00:00Z"))
    two = rerun_after_decision(base, [decision], CFG, FixedClock("2020-01-01T00:00:00Z"))
    assert one.manifest_hash == two.manifest_hash
