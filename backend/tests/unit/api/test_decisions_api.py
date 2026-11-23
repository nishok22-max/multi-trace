"""D-05: the decision route end to end. Named: test_viewer_decision_403,
test_spoofed_reviewer_field_422, test_choice_validated_against_item,
test_decision_evidence_changed_409, test_20_parallel_decisions_one_wins,
test_stale_base_version_untouched_item_accepted, test_supersede_requires_senior,
test_decision_during_build_returns_409."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.api.test_auth import CSRF, PASSWORD
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api import deps
from trace_api.main import create_app
from trace_api.security.sessions import AuthRepository
from trace_core.ids import build_claim, review_id
from trace_core.models.case import VersionRecords
from trace_core.models.claims import Candidate, MentionKey, Subject
from trace_core.models.records import ReviewItem

KEY = MentionKey(source_sha256="a" * 64, locator="p1:10-18")
CANDIDATES = [Candidate(entity_id="machine:21", score=0.6)]
HASH = "b" * 64


class Setup:
    def __init__(self, root: Path, world: World, item: ReviewItem) -> None:
        self.root = root
        self.world = world
        self.item = item
        self.clock = FixedClock("2015-08-06T05:00:00Z")
        self.repo = AuthRepository(root / "trace.db", self.clock)
        for user, role in (
            ("rita", "reviewer"),
            ("sam", "senior_reviewer"),
            ("vik", "viewer"),
        ):
            self.repo.create_user(f"u-{user}", user, user.title(), role, PASSWORD)  # type: ignore[arg-type]

    @property
    def case(self) -> str:
        return self.world.case_id

    def url(self, rid: str | None = None) -> str:
        return f"/api/v1/cases/{self.case}/review/{rid or self.item.review_id}/decision"

    def body(self, **over: Any) -> dict[str, Any]:
        base = {
            "choice": {"type": "entity", "entity_id": "machine:21"},
            "reason": "Line 2 names machine 21; the serial matches the register",
            "base_version": 1,
            "shown_evidence_hash": HASH,
        }
        return {**base, **over}


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    world = synthetic_world(tmp_path, spike=False)
    version = build_version(world)
    text = next(c for c in version.records.claims if c.modality == "text")
    fields = text.model_dump(mode="python")
    fields["subject"] = Subject(
        mention="Press 21",
        entity_id=None,
        link_status="ambiguous",
        candidates=CANDIDATES,
        mention_key=KEY,
    )
    ambiguous = build_claim(**fields)
    item = ReviewItem(
        review_id=review_id("ambiguous_entity", [KEY]),
        type="ambiguous_entity",
        claim_ids=[ambiguous.claim_id],
        mention_keys=[KEY],
        candidates=CANDIDATES,
        evidence_hash=HASH,
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
    world.store.commit_build(version.model_copy(update={"records": records}), world.manifest())
    return Setup(tmp_path, world, item)


def _client(setup: Setup, user: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: setup.repo
    client = TestClient(app, base_url="http://127.0.0.1")
    res = client.post(
        "/api/v1/auth/login", json={"username": user, "password": PASSWORD}, headers=CSRF
    )
    assert res.status_code == 200
    return client


@pytest.fixture
def rita(setup: Setup, loopback_only: None) -> Iterator[TestClient]:
    with _client(setup, "rita") as c:
        yield c


def test_a_reviewer_decision_relinks_and_makes_a_new_version(
    setup: Setup, rita: TestClient
) -> None:
    res = rita.post(setup.url(), json=setup.body(), headers=CSRF)
    assert res.status_code == 201 and res.headers["cache-control"] == "no-store"
    assert res.json()["version"] == 2
    store = SqliteClaimStore(setup.root / "trace.db")
    v2 = store.get_version(setup.case, 2)
    assert v2 is not None and [c.outcome for c in v2.records.comparisons] == ["agree"]
    (decision,) = v2.records.decisions
    assert decision.principal.sub == "u-rita" and decision.role_snapshot == "reviewer"
    assert decision.display_name_snapshot == "Rita"  # identity from the session only


def test_viewer_decision_403(setup: Setup, loopback_only: None) -> None:
    with _client(setup, "vik") as viewer:
        assert viewer.post(setup.url(), json=setup.body(), headers=CSRF).status_code == 403


def test_decision_needs_a_session(setup: Setup, loopback_only: None) -> None:
    with TestClient(create_app(), base_url="http://127.0.0.1") as anon:
        assert anon.post(setup.url(), json=setup.body(), headers=CSRF).status_code == 401


def test_spoofed_reviewer_field_422(setup: Setup, rita: TestClient) -> None:
    res = rita.post(setup.url(), json=setup.body(reviewer="someone-else"), headers=CSRF)
    assert res.status_code == 422


def test_choice_validated_against_item(setup: Setup, rita: TestClient) -> None:
    wrong = setup.body(choice={"type": "reading", "verdict": "accept"})
    assert rita.post(setup.url(), json=wrong, headers=CSRF).status_code == 422
    assert (
        rita.post(setup.url("rv_" + "0" * 24), json=setup.body(), headers=CSRF).status_code == 404
    )


def test_decision_evidence_changed_409(setup: Setup, rita: TestClient) -> None:
    res = rita.post(setup.url(), json=setup.body(shown_evidence_hash="c" * 64), headers=CSRF)
    assert res.status_code == 409 and res.json()["type"] == "/problems/evidence-changed"


def test_second_decision_is_already_decided(setup: Setup, rita: TestClient) -> None:
    assert rita.post(setup.url(), json=setup.body(), headers=CSRF).status_code == 201
    again = rita.post(
        setup.url(), json=setup.body(reason="a different but long enough reason"), headers=CSRF
    )
    assert again.status_code == 409 and again.json()["type"] == "/problems/already-decided"


def test_stale_base_version_untouched_item_accepted(setup: Setup, rita: TestClient) -> None:
    """The latest is v1; a client that saw an older base still decides if the item is unchanged."""
    res = rita.post(setup.url(), json=setup.body(base_version=0), headers=CSRF)
    assert res.status_code == 201
    future = rita.post(setup.url("rv_" + "1" * 24), json=setup.body(base_version=99), headers=CSRF)
    assert future.status_code in (404, 422)


def test_supersede_requires_senior(setup: Setup, rita: TestClient, loopback_only: None) -> None:
    assert rita.post(setup.url(), json=setup.body(), headers=CSRF).status_code == 201
    first = SqliteClaimStore(setup.root / "trace.db").latest(setup.case)
    assert first is not None
    prior = first.records.decisions[0].decision_id
    redo = setup.body(
        choice={"type": "entity", "entity_id": "machine:21"},
        reason="Re-checked the register, the same machine after all",
        supersedes=prior,
    )
    assert rita.post(setup.url(), json=redo, headers=CSRF).status_code == 403
    with _client(setup, "sam") as senior:
        assert senior.post(setup.url(), json=redo, headers=CSRF).status_code == 201


def test_decision_during_build_returns_409(setup: Setup, rita: TestClient) -> None:
    conn = sqlite3.connect(setup.root / "trace.db")
    conn.execute(
        "INSERT INTO builds(build_id, case_id, build_key, status, started_at, heartbeat_at,"
        " stage_ms, counters) VALUES ('b1', ?, 'k1', 'running', 't', 't', '{}', '{}')",
        (setup.case,),
    )
    conn.commit()
    conn.close()
    res = rita.post(setup.url(), json=setup.body(), headers=CSRF)
    assert res.status_code == 409 and res.json()["type"] == "/problems/build-in-progress"
    assert res.headers["retry-after"] == "5"


def test_20_parallel_decisions_one_wins(setup: Setup, loopback_only: None) -> None:
    for n in range(20):
        setup.repo.create_user(f"u-p{n}", f"p{n}", f"P{n}", "reviewer", PASSWORD)
    clients = [_client(setup, f"p{n}") for n in range(20)]
    statuses: list[int] = []
    lock = threading.Lock()

    def fire(client: TestClient) -> None:
        res = client.post(setup.url(), json=setup.body(), headers=CSRF)
        with lock:
            statuses.append(res.status_code)

    threads = [threading.Thread(target=fire, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses.count(201) == 1 and statuses.count(409) == 19, statuses
    latest = SqliteClaimStore(setup.root / "trace.db").latest(setup.case)
    assert latest is not None and latest.version == 2  # exactly one new version


def test_review_queue_status_is_derived_not_stored(setup: Setup, rita: TestClient) -> None:
    url = f"/api/v1/cases/{setup.case}/versions/1/review"
    queue = rita.get(url)
    assert queue.status_code == 200 and queue.headers["cache-control"] == "no-store"
    (entry,) = queue.json()
    assert entry["item"]["review_id"] == setup.item.review_id
    assert entry["status"] in ("open", "escalated")  # never a stored field
    assert rita.post(setup.url(), json=setup.body(), headers=CSRF).status_code == 201
    after = rita.get(f"/api/v1/cases/{setup.case}/versions/2/review").json()
    assert [e["status"] for e in after] == ["decided"]
