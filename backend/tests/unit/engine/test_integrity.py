"""D-04: integrity re-walk. Named: test_chain_verify_detects_edit, test_snapshot_hash_mismatch,
test_manifest_covers_review_events (review items and decisions),
test_integrity_verifies_stored_bytes, plus the clock-independence of the manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.factories import make_decision, make_review_item
from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_gate import CFG
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.pdfium_reader import PdfiumReader
from trace_core.build import build_case
from trace_core.models.case import CaseVersion
from trace_core.models.records import ReadingChoice
from trace_core.snapshot.integrity import snapshot_matches, verify_chain
from trace_worker.env import snapshot_hashes


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory) -> tuple[World, CaseVersion, CaseVersion]:
    world = synthetic_world(tmp_path_factory.mktemp("integrity"), spike=False)
    v1 = build_version(world)
    v2 = build_case(
        world.manifest(),
        CFG,
        [],
        world.ports(),
        parent=v1,
        hashes=snapshot_hashes(CFG, PdfiumReader.binary_version()),
    )
    return world, v1, v2


def _stored_sha(world: World):  # type: ignore[no-untyped-def]
    blobs = world.ports().blobs

    def sha(key: str) -> str | None:
        if not blobs.exists(key):
            return None
        return hashlib.sha256(blobs.open(key).read()).hexdigest()

    return sha


def test_an_untouched_chain_verifies(chain: tuple[World, CaseVersion, CaseVersion]) -> None:
    world, v1, v2 = chain
    result = verify_chain([v1, v2], _stored_sha(world))
    assert result.ok and result.version == 2 and result.failures == []
    assert v2.parent_manifest_hash == v1.manifest_hash and v1.manifest_hash != v2.manifest_hash


def test_chain_verify_detects_edit(chain: tuple[World, CaseVersion, CaseVersion]) -> None:
    _, v1, v2 = chain
    claim = v1.records.claims[0]
    edited = claim.model_copy(update={"statement": claim.statement + " (edited)"})
    tampered = v1.model_copy(
        update={
            "records": v1.records.model_copy(update={"claims": [edited, *v1.records.claims[1:]]})
        }
    )
    result = verify_chain([tampered, v2])
    assert not result.ok and not result.snapshot_ok  # the manifest no longer matches
    # changing a hashed field breaks the per-claim hash too
    broken = claim.model_copy(update={"value": "tampered"})
    result = verify_chain(
        [
            v1.model_copy(
                update={
                    "records": v1.records.model_copy(
                        update={"claims": [broken, *v1.records.claims[1:]]}
                    )
                }
            ),
            v2,
        ]
    )
    assert not result.records_ok and any("fails its hash" in f for f in result.failures)


def test_chain_break_is_reported(chain: tuple[World, CaseVersion, CaseVersion]) -> None:
    _, v1, v2 = chain
    detached = v2.model_copy(update={"parent_manifest_hash": "0" * 64})
    result = verify_chain([v1, detached])
    assert not result.chain_ok and any("does not link" in f for f in result.failures)
    assert not verify_chain([v2]).chain_ok  # a v2 that claims a parent cannot start the chain


def test_snapshot_hash_mismatch(chain: tuple[World, CaseVersion, CaseVersion]) -> None:
    _, v1, _ = chain
    assert snapshot_matches(v1)
    forged = v1.model_copy(update={"manifest_hash": "f" * 64})
    assert not snapshot_matches(forged)
    assert not verify_chain([forged]).snapshot_ok


def test_manifest_covers_review_items_and_decisions(
    chain: tuple[World, CaseVersion, CaseVersion],
) -> None:
    _, v1, _ = chain
    item = make_review_item([v1.records.claims[0].claim_id])
    with_item = v1.model_copy(
        update={"records": v1.records.model_copy(update={"review_items": [item]})}
    )
    assert not snapshot_matches(with_item)  # the stored manifest does not cover this item
    decision = make_decision(item, ReadingChoice(verdict="accept"))
    with_decision = with_item.model_copy(
        update={
            "records": with_item.records.model_copy(update={"decisions": [decision]}),
        }
    )
    assert with_decision.records.decisions and not snapshot_matches(with_decision)


def test_integrity_verifies_stored_bytes(
    chain: tuple[World, CaseVersion, CaseVersion], tmp_path: Path
) -> None:
    world, v1, v2 = chain
    sources = [
        s for s in world.manifest().sources if s.held_reason is None and s.modality != "sensor"
    ]
    victim = sources[0]
    blobs = world.ports().blobs
    assert blobs.exists(victim.sha256)
    wrong = lambda key: "0" * 64 if key == victim.sha256 else _stored_sha(world)(key)  # noqa: E731
    result = verify_chain([v1, v2], wrong)
    assert not result.ok and any(victim.source_id in f for f in result.failures)
    missing = lambda key: None if key == victim.sha256 else _stored_sha(world)(key)  # noqa: E731
    assert not verify_chain([v1, v2], missing).ok


def test_manifest_is_independent_of_the_clock(
    chain: tuple[World, CaseVersion, CaseVersion],
) -> None:
    world, v1, _ = chain
    ports = world.ports()
    ports = (
        ports.model_copy(update={"clock": FixedClock("2030-01-01T00:00:00Z")})
        if hasattr(ports, "model_copy")
        else ports.__class__(**{**ports.__dict__, "clock": FixedClock("2030-01-01T00:00:00Z")})
    )
    again = build_case(
        world.manifest(),
        CFG,
        [],
        ports,
        hashes=snapshot_hashes(CFG, PdfiumReader.binary_version()),
    )
    assert again.manifest_hash == v1.manifest_hash
    assert again.created_at != v1.created_at
