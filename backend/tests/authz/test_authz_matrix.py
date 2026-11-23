"""Authorisation matrix (TEST_PLAN 4.5, `make authz`) and the evaluation single-flight test.
Named: test_authz_matrix, test_parallel_eval_runs_one_proceeds, test_eval_report_is_evaluator_only.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.factories import make_case
from tests.unit.api.test_auth import CSRF, PASSWORD
from tests.unit.api.test_proof_api import Setup
from trace_api import deps
from trace_api.main import create_app
from trace_api.routers import claims as claims_router
from trace_api.services.recheck import RateLimiter

ROLES = ("viewer", "reviewer", "senior_reviewer", "ingestor", "evaluator")
CASE = "case-m21-2015-08-05"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None) -> Setup:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    s = Setup(tmp_path)
    for role in ROLES:
        if role not in ("viewer", "evaluator"):
            s.repo.create_user(f"u-{role}", role, role.title(), role, PASSWORD)  # type: ignore[arg-type]
    return s


def _client(setup: Setup, role: str | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: setup.repo
    claims_router.LIMITER = RateLimiter()
    client = TestClient(app, base_url="http://127.0.0.1")
    if role is not None:
        name = {"viewer": "vik", "evaluator": "eve"}.get(role, role)
        res = client.post(
            "/api/v1/auth/login", json={"username": name, "password": PASSWORD}, headers=CSRF
        )
        assert res.status_code == 200, role
    return client


# route -> (method, url, body); the expected status per role (None = anonymous)
def _routes(case: str, claim_id: str) -> dict[str, tuple[str, str, dict[str, object] | None]]:
    base = f"/api/v1/cases/{case}"
    return {
        "read_state": ("get", f"{base}/versions/1/state", None),
        "read_claim": ("get", f"{base}/versions/1/claims/{claim_id}", None),
        "evidence": ("get", f"{base}/versions/1/claims/{claim_id}/evidence", None),
        "integrity": ("get", f"{base}/versions/1/integrity", None),
        "cases": ("get", "/api/v1/cases", None),
        "start_build": ("post", f"{base}/build", None),
        "replay": ("post", f"{base}/versions/1/replay", None),
        "eval_report": ("get", "/api/v1/eval/report", None),
        "decide": (
            "post",
            f"{base}/review/rv_{'0' * 24}/decision",
            {
                "choice": {"type": "escalate"},
                "reason": "needs a senior look at this item",
                "base_version": 1,
                "shown_evidence_hash": "0" * 64,
            },
        ),
    }


EXPECTED = {
    # route:        anon, viewer, reviewer, senior, ingestor, evaluator
    "read_state": (401, 200, 200, 200, 200, 200),
    "read_claim": (401, 200, 200, 200, 200, 200),
    "evidence": (401, 200, 200, 200, 200, 200),
    "integrity": (401, 200, 200, 200, 200, 200),
    "cases": (401, 200, 200, 200, 200, 200),
    "start_build": (401, 403, 403, 403, None, 403),  # ingestor: 202/409, never 401/403
    "replay": (401, 403, 403, 403, 403, 200),
    "eval_report": (401, 403, 403, 403, 403, 404),  # evaluator: allowed, no report yet
    "decide": (401, 403, 404, 404, 403, 403),  # reviewers pass the role gate, then 404
}


def test_authz_matrix(setup: Setup) -> None:
    claim = next(c for c in setup.version.records.claims if c.modality == "text")
    routes = _routes(setup.case, claim.claim_id)
    for who in (None, *ROLES):
        client = _client(setup, who)
        column = 0 if who is None else 1 + ROLES.index(who)
        for name, (method, url, body) in routes.items():
            if name == "replay" and who not in (None, "evaluator"):
                pass  # the replay child only runs for the evaluator; the others stop at 403
            want = EXPECTED[name][column]
            res = getattr(client, method)(url, headers=CSRF, **({"json": body} if body else {}))
            if want is None:
                assert res.status_code in (202, 409), (name, who, res.status_code)
            else:
                assert res.status_code == want, (name, who, res.status_code, res.text[:200])
        client.close()


def test_another_cases_ids_are_404_not_403(setup: Setup) -> None:
    claim = next(c for c in setup.version.records.claims if c.modality == "text")
    client = _client(setup, "viewer")
    other = make_case("case-other").case_id
    assert client.get(f"/api/v1/cases/{other}/versions/1/state").status_code == 404
    assert (
        client.get(f"/api/v1/cases/{setup.case}/versions/1/claims/clm_{'f' * 24}").status_code
        == 404
    )
    assert claim.claim_id.startswith("clm_")


@pytest.fixture
def evaluator(setup: Setup) -> Iterator[TestClient]:
    client = _client(setup, "evaluator")
    yield client
    client.close()


def test_parallel_eval_runs_one_proceeds(setup: Setup, evaluator: TestClient) -> None:
    """Two simultaneous runs: one 202, one 409 (the database is the lock)."""
    other = _client(setup, "evaluator")
    codes: list[int] = []
    lock = threading.Lock()

    def start(client: TestClient) -> None:
        res = client.post("/api/v1/eval/run", headers=CSRF)
        with lock:
            codes.append(res.status_code)

    threads = [threading.Thread(target=start, args=(c,)) for c in (evaluator, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [202, 409], codes
    report = setup.root / "eval_report.json"
    deadline = time.monotonic() + 240
    while not report.is_file() and time.monotonic() < deadline:
        time.sleep(1)
    assert report.is_file(), "the accepted run never finished"
    got = evaluator.get("/api/v1/eval/report")
    assert got.status_code == 200 and got.json()["split"] == "dev"
    assert got.headers["cache-control"] == "no-store"
    time.sleep(2)  # let the watcher record `done`, then a new run is accepted again
    again = evaluator.post("/api/v1/eval/run", headers=CSRF)
    assert again.status_code == 202
    other.close()


def test_eval_report_is_evaluator_only(setup: Setup) -> None:
    for role in ("viewer", "reviewer", "ingestor"):
        client = _client(setup, role)
        assert client.get("/api/v1/eval/report").status_code == 403
        assert client.post("/api/v1/eval/run", headers=CSRF).status_code == 403
        client.close()
