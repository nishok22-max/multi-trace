"""D-05 concurrency and latency budgets (serial; `make check-perf`). Named:
test_decisions_on_two_cases_parallel_no_locked_error, test_proof_p95_under_1s_during_decision,
test_decision_during_build_other_case_p95_under_2s.

Each case gets its own document, because a review item is keyed by (document, locator): two cases
that shared one blob would share one review item."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.api.test_auth import CSRF, PASSWORD
from tools.e2e_server import BASE_LINES, report
from trace_adapters.fakes.clock import FixedClock
from trace_api import deps
from trace_api.main import create_app
from trace_api.security.sessions import AuthRepository
from trace_core.models.case import CaseVersion

pytestmark = pytest.mark.perf


class Cases:
    def __init__(self, root: Path, count: int) -> None:
        self.root = root
        self.versions: dict[str, CaseVersion] = {}
        self.worlds: dict[str, World] = {}
        for n in range(count):
            case = f"case-p{n}"
            world = synthetic_world(
                root, case_id=case, report=report([*BASE_LINES, f"Perf note {n}."]), spike=True
            )
            version = build_version(world)
            world.store.commit_build(version, world.manifest())
            self.versions[case], self.worlds[case] = version, world
        self.repo = AuthRepository(root / "trace.db", FixedClock("2015-08-06T05:00:00Z"))
        self.repo.create_user("u-rita", "rita", "Rita", "reviewer", PASSWORD)

    def item(self, case: str):  # type: ignore[no-untyped-def]
        (item,) = self.versions[case].records.review_items
        return item

    def client(self) -> TestClient:
        app = create_app()
        app.dependency_overrides[deps.get_auth_repo] = lambda: self.repo
        client = TestClient(app, base_url="http://127.0.0.1")
        client.post(
            "/api/v1/auth/login", json={"username": "rita", "password": PASSWORD}, headers=CSRF
        )
        return client

    def decide(self, client: TestClient, case: str) -> tuple[int, float]:
        item = self.item(case)
        body = {
            "choice": {"type": "entity", "entity_id": "machine:21"},
            "reason": "The register lists Press 21 as machine 21 on line 2.",
            "base_version": 1,
            "shown_evidence_hash": item.evidence_hash,
        }
        started = time.perf_counter()
        res = client.post(
            f"/api/v1/cases/{case}/review/{item.review_id}/decision", json=body, headers=CSRF
        )
        return res.status_code, time.perf_counter() - started


@pytest.fixture
def cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None) -> Cases:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    return Cases(tmp_path, 6)


def test_decisions_on_two_cases_parallel_no_locked_error(cases: Cases) -> None:
    results: dict[str, tuple[int, float]] = {}
    clients = {c: cases.client() for c in ("case-p0", "case-p1")}

    def run(case: str) -> None:
        results[case] = cases.decide(clients[case], case)

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {c: r[0] for c, r in results.items()} == {"case-p0": 201, "case-p1": 201}
    for case in clients:  # each case moved to its own version 2 and nothing else changed
        latest = cases.worlds[case].store.latest(case)
        assert latest is not None and latest.version == 2


def test_proof_p95_under_1s_during_decision(cases: Cases) -> None:
    reader = cases.client()
    writer = cases.client()
    claim = next(c for c in cases.versions["case-p0"].records.claims if c.modality == "text")
    url = f"/api/v1/cases/case-p0/versions/1/claims/{claim.claim_id}/evidence"
    stop = threading.Event()
    codes: list[int] = []

    def decide_others() -> None:
        for case in ("case-p1", "case-p2", "case-p3", "case-p4"):
            codes.append(cases.decide(writer, case)[0])
        stop.set()

    thread = threading.Thread(target=decide_others)
    thread.start()
    samples: list[float] = []
    while not stop.is_set() or len(samples) < 20:
        started = time.perf_counter()
        assert reader.get(url).status_code == 200
        samples.append(time.perf_counter() - started)
    thread.join()
    assert codes == [201, 201, 201, 201]
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    assert p95 < 1.0, f"proof p95 {p95:.3f} s over {len(samples)} reads"


def test_decision_during_build_other_case_p95_under_2s(cases: Cases) -> None:
    conn = sqlite3.connect(cases.root / "trace.db")
    conn.execute(
        "INSERT INTO builds(build_id, case_id, build_key, status, started_at, heartbeat_at,"
        " stage_ms, counters) VALUES ('bx', 'case-p0', 'kx', 'running', 't', 't', '{}', '{}')"
    )
    conn.commit()
    conn.close()
    client = cases.client()
    blocked, _ = cases.decide(client, "case-p0")
    assert blocked == 409  # the case that is being built waits
    samples = []
    for case in ("case-p1", "case-p2", "case-p3", "case-p4", "case-p5"):
        code, took = cases.decide(client, case)
        assert code == 201  # another case's build never blocks this one
        samples.append(took)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    assert p95 < 2.0, f"decision p95 {p95:.3f} s"
