"""The last two contract stubs: `POST /cases` (ingestor) and `/readyz`; and the guarantee that no
route answers 501 any more (every contract route is a real service)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.test_auth import CSRF, PASSWORD
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api import deps
from trace_api.main import create_app
from trace_api.routers import health
from trace_api.security.sessions import AuthRepository

BODY = {
    "case_id": "case-new-0001",
    "title": "Machine 7, 9 June 2015",
    "entities": ["machine:7"],
    "window_start": "2015-06-08T18:30:00Z",
    "window_end": "2015-06-09T18:30:00Z",
    "plant_tz": "Asia/Kolkata",
}


@pytest.fixture
def client_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None
) -> Iterator[object]:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    SqliteClaimStore(tmp_path / "trace.db")
    repo = AuthRepository(tmp_path / "trace.db", FixedClock("2015-08-06T05:00:00Z"))
    repo.create_user("u-ina", "ina", "Ina", "ingestor", PASSWORD)
    repo.create_user("u-vik", "vik", "Vik", "viewer", PASSWORD)
    clients: list[TestClient] = []

    def make(user: str | None) -> TestClient:
        app = create_app()
        app.dependency_overrides[deps.get_auth_repo] = lambda: repo
        c = TestClient(app, base_url="http://127.0.0.1")
        if user:
            c.post(
                "/api/v1/auth/login", json={"username": user, "password": PASSWORD}, headers=CSRF
            )
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()


def test_an_ingestor_creates_a_case_once(client_for) -> None:  # type: ignore[no-untyped-def]
    ingestor = client_for("ina")
    created = ingestor.post("/api/v1/cases", json=BODY, headers=CSRF)
    assert created.status_code == 201 and created.json()["case_id"] == BODY["case_id"]
    assert created.headers["cache-control"] == "no-store"
    again = ingestor.post("/api/v1/cases", json=BODY, headers=CSRF)
    assert again.status_code == 409 and again.json()["type"] == "/problems/append-only"
    listing = ingestor.get("/api/v1/cases").json()["cases"]
    assert [c["case_id"] for c in listing] == [BODY["case_id"]]


def test_only_ingestors_create_cases(client_for) -> None:  # type: ignore[no-untyped-def]
    assert client_for("vik").post("/api/v1/cases", json=BODY, headers=CSRF).status_code == 403
    assert client_for(None).post("/api/v1/cases", json=BODY, headers=CSRF).status_code == 401
    bad = {**BODY, "case_id": "Not Valid!"}
    assert client_for("ina").post("/api/v1/cases", json=bad, headers=CSRF).status_code == 422


def test_readyz_reports_each_flag(client_for, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    anon = client_for(None)
    res = anon.get("/readyz")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    body = res.json()
    assert set(body) == {"db_writable", "blobs_writable", "tesseract_present", "disk_ok"}
    assert body["db_writable"] and body["blobs_writable"] and body["disk_ok"]
    monkeypatch.setattr(health, "ensure_free_space", lambda *_a, **_k: False)
    low = anon.get("/readyz")
    assert low.status_code == 503 and low.json()["disk_ok"] is False  # under 1 GB free: not ready


def test_no_contract_route_answers_501_any_more() -> None:
    routers = Path(__file__).resolve().parents[3] / "trace_api" / "routers"
    for path in sorted(routers.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"return\s+not_implemented\(\)", text), path.name
