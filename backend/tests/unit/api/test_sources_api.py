"""A-07 over HTTP: upload, classify, store by hash, hardened download, role and case scoping."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.factories import make_case
from tests.unit.api.test_auth import CSRF, PASSWORD, Env
from trace_api import deps
from trace_api.main import create_app

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"
CASE = make_case().case_id


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    e = Env(tmp_path)
    e.repo.create_user("u-ina", "ina", "Ina Ingestor", "ingestor", PASSWORD)
    return e


@pytest.fixture
def api(env: Env, loopback_only: None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: env.repo
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def _login(api: TestClient, user: str) -> None:
    res = api.post(
        "/api/v1/auth/login", json={"username": user, "password": PASSWORD}, headers=CSRF
    )
    assert res.status_code == 200


def _upload(api: TestClient, name: str, data: bytes, query: str = "") -> object:
    return api.post(
        f"/api/v1/cases/{CASE}/sources{query}",
        files={"file": (name, data, "application/octet-stream")},
        headers=CSRF,
    )


def test_ingestor_uploads_a_pdf_stored_by_hash(api: TestClient, env: Env) -> None:
    _login(api, "ina")
    res = _upload(api, "../../report.pdf", PDF)
    assert res.status_code == 201  # type: ignore[attr-defined]
    body = res.json()  # type: ignore[attr-defined]
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
    stored = env.root / "blobs" / body["sha256"][:2] / body["sha256"]
    assert stored.read_bytes() == PDF  # hash-only path, no client-supplied name on disk
    manifest = api.app.dependency_overrides  # noqa: F841 (the app is reused below)
    original = api.get(f"/api/v1/cases/{CASE}/sources/{body['source_id']}/original")
    assert original.status_code == 200 and original.content == PDF
    assert original.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert original.headers["content-type"] == "application/octet-stream"
    assert original.headers["content-security-policy"].startswith("sandbox")
    assert original.headers["x-content-type-options"] == "nosniff"


def test_telemetry_kind_marks_a_csv_as_sensor(api: TestClient, env: Env) -> None:
    from trace_adapters.sqlite.store import SqliteClaimStore

    _login(api, "ina")
    csv = b'"datetime","machineID","volt"\n2015-01-01 06:00:00,21,1.0\n'
    assert _upload(api, "t.csv", csv, "?kind=telemetry").status_code == 201  # type: ignore[attr-defined]
    assert _upload(api, "e.csv", csv).status_code == 201  # type: ignore[attr-defined]
    manifest = SqliteClaimStore(env.root / "trace.db").load_manifest(CASE)
    assert manifest is not None
    assert sorted(s.modality for s in manifest.sources) == ["sensor", "table"]


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("evil.pdf", b"<html><script>alert(1)</script></html>"),
        ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("renamed.csv", PDF),
    ],
)
def test_hostile_uploads_are_415_problems(api: TestClient, name: str, data: bytes) -> None:
    _login(api, "ina")
    res = _upload(api, name, data)
    assert res.status_code == 415  # type: ignore[attr-defined]
    assert res.headers["content-type"].startswith("application/problem+json")  # type: ignore[attr-defined]
    assert res.json()["type"] == "/problems/unsupported-media"  # type: ignore[attr-defined]


def test_only_ingestors_upload(api: TestClient) -> None:
    _login(api, "vik")
    assert _upload(api, "report.pdf", PDF).status_code == 403  # type: ignore[attr-defined]


def test_upload_needs_a_session_and_csrf(api: TestClient) -> None:
    assert _upload(api, "report.pdf", PDF).status_code == 401  # type: ignore[attr-defined]
    res = api.post(f"/api/v1/cases/{CASE}/sources", files={"file": ("r.pdf", PDF)})
    assert res.status_code == 403  # no CSRF header


def test_cross_case_source_download_is_404(api: TestClient) -> None:
    _login(api, "ina")
    sid = _upload(api, "report.pdf", PDF).json()["source_id"]  # type: ignore[attr-defined]
    assert api.get(f"/api/v1/cases/{CASE}/sources/{sid}/original").status_code == 200
    other = api.get(f"/api/v1/cases/{CASE}/sources/src-unknown/original")
    assert other.status_code == 404
    assert other.headers["content-type"].startswith("application/problem+json")
