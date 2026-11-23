"""M4 backend: the proof routes. Named: test_page_png_cache_miss_404_not_render,
test_recheck_re_derives_value, test_recheck_rate_limited, plus evidence rows, replay and cases."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.api.test_auth import CSRF, PASSWORD
from trace_adapters.fakes.clock import FixedClock
from trace_api import deps
from trace_api.main import create_app
from trace_api.routers import claims as claims_router
from trace_api.security.sessions import AuthRepository
from trace_api.services.recheck import RateLimiter
from trace_core.models.case import CaseVersion
from trace_worker.prerender import prerender
from trace_worker.render_paths import page_png_path


class Setup:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.world: World = synthetic_world(root, spike=True)
        self.version: CaseVersion = build_version(self.world)
        self.world.store.commit_build(self.version, self.world.manifest())
        clock = FixedClock("2015-08-06T05:00:00Z")
        self.repo = AuthRepository(root / "trace.db", clock)
        self.repo.create_user("u-eve", "eve", "Eve Evaluator", "evaluator", PASSWORD)
        self.repo.create_user("u-vik", "vik", "Vik Viewer", "viewer", PASSWORD)

    @property
    def case(self) -> str:
        return self.world.case_id

    def claim(self, modality: str, extracted: bool = True):  # type: ignore[no-untyped-def]
        return next(
            c
            for c in self.version.records.claims
            if c.modality == modality and (c.claim_type == "extracted") == extracted
        )

    def url(self, claim_id: str, tail: str, v: int = 1) -> str:
        return f"/api/v1/cases/{self.case}/versions/{v}/claims/{claim_id}/{tail}"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    return Setup(tmp_path)


@pytest.fixture
def api(setup: Setup, loopback_only: None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: setup.repo
    claims_router.LIMITER = RateLimiter()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post(
            "/api/v1/auth/login", json={"username": "eve", "password": PASSWORD}, headers=CSRF
        )
        yield client


def test_page_png_cache_miss_404_not_render(setup: Setup, api: TestClient) -> None:
    text = setup.claim("text")
    miss = api.get(setup.url(text.claim_id, "evidence/page.png"))
    assert miss.status_code == 404 and miss.json()["type"] == "/problems/render-missing"
    ev = api.get(setup.url(text.claim_id, "evidence")).json()
    assert ev["render_status"] == "missing" and ev["page_png"] is None  # nothing was rendered
    prerender(setup.version, setup.world.ports().blobs, setup.root / "renders")
    hit = api.get(setup.url(text.claim_id, "evidence/page.png"))
    assert hit.status_code == 200 and hit.headers["content-type"] == "image/png"
    assert hit.content.startswith(b"\x89PNG")
    assert (
        "immutable" in hit.headers["cache-control"] and "public" not in hit.headers["cache-control"]
    )
    assert (
        api.get(
            setup.url(text.claim_id, "evidence/page.png"),
            headers={"If-None-Match": hit.headers["etag"]},
        ).status_code
        == 304
    )
    ev = api.get(setup.url(text.claim_id, "evidence")).json()
    assert ev["render_status"] == "cached" and ev["page_png"].endswith("/evidence/page.png")


def test_evidence_rows_for_tables_and_sensor_windows(setup: Setup, api: TestClient) -> None:
    table = setup.claim("table")
    rows = api.get(setup.url(table.claim_id, "evidence")).json()["window_rows"]
    assert rows and {"row", "datetime", "machineID"} <= set(rows[0])
    cited = table.evidence.row  # type: ignore[union-attr]
    assert any(r["row"] == cited for r in rows) and len(rows) <= 51  # +-25 rows around the cell
    window = next(
        c
        for c in setup.version.records.claims
        if c.modality == "sensor" and c.claim_type == "extracted" and c.attribute == "vibration"
    )
    sensor = api.get(setup.url(window.claim_id, "evidence")).json()["window_rows"]
    assert len(sensor) == 24 and set(sensor[0]) == {"ts", "vibration"}  # hourly readings, raw


def test_recheck_re_derives_value(setup: Setup, api: TestClient) -> None:
    text = setup.claim("text")
    prerender(setup.version, setup.world.ports().blobs, setup.root / "renders")
    ok = api.post(setup.url(text.claim_id, "recheck", 0).replace("/versions/0", ""), headers=CSRF)
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    assert ok.json() == {
        "match": True,
        "source_sha_ok": True,
        "artifact_sha_ok": True,
        "input_sha_ok": True,
        "value_ok": True,
    }
    for modality, extracted in (("table", True), ("sensor", True), ("sensor", False)):
        claim = setup.claim(modality, extracted)
        got = api.post(
            setup.url(claim.claim_id, "recheck", 0).replace("/versions/0", ""), headers=CSRF
        )
        assert got.json()["match"] is True, (modality, extracted, got.json())


def test_a_flipped_byte_is_evidence_changed(setup: Setup, api: TestClient) -> None:
    text = setup.claim("text")
    prerender(setup.version, setup.world.ports().blobs, setup.root / "renders")
    sha = text.evidence.sha256  # type: ignore[union-attr]
    blob = setup.root / "blobs" / sha[:2] / sha
    data = bytearray(blob.read_bytes())
    data[len(data) // 2] ^= 0xFF
    blob.write_bytes(bytes(data))
    url = setup.url(text.claim_id, "recheck", 0).replace("/versions/0", "")
    bad = api.post(url, headers=CSRF).json()
    assert bad["match"] is False and bad["source_sha_ok"] is False
    table = setup.claim("table")
    tsha = table.evidence.sha256  # type: ignore[union-attr]
    path = setup.root / "blobs" / tsha[:2] / tsha
    path.write_bytes(path.read_bytes().replace(b"2015", b"2016", 1))
    got = api.post(setup.url(table.claim_id, "recheck", 0).replace("/versions/0", ""), headers=CSRF)
    assert got.json()["match"] is False


def test_recheck_rate_limited(setup: Setup, api: TestClient) -> None:
    text = setup.claim("text")
    url = setup.url(text.claim_id, "recheck", 0).replace("/versions/0", "")
    codes = [api.post(url, headers=CSRF).status_code for _ in range(32)]
    assert codes.count(200) == 30 and codes[-2:] == [429, 429]
    limited = api.post(url, headers=CSRF)
    assert (
        limited.json()["type"] == "/problems/rate-limited"
        and limited.headers["retry-after"] == "60"
    )


def test_recheck_unknown_claim_is_404(setup: Setup, api: TestClient) -> None:
    res = api.post(f"/api/v1/cases/{setup.case}/claims/clm_{'0' * 24}/recheck", headers=CSRF)
    assert res.status_code == 404


def test_rate_limiter_window() -> None:
    limiter = RateLimiter(limit=2, window=10.0)
    assert limiter.allow("a", 0.0) and limiter.allow("a", 1.0) and not limiter.allow("a", 2.0)
    assert limiter.allow("b", 2.0)  # per key
    assert limiter.allow("a", 10.5)  # the first hit left the window


def test_cases_list_needs_a_session(setup: Setup, api: TestClient, loopback_only: None) -> None:
    listing = api.get("/api/v1/cases")
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    assert [c["case_id"] for c in listing.json()["cases"]] == [setup.case]
    with TestClient(create_app(), base_url="http://127.0.0.1") as anon:
        assert anon.get("/api/v1/cases").status_code == 401


def test_replay_matches_and_needs_the_evaluator_role(setup: Setup, api: TestClient) -> None:
    res = api.post(f"/api/v1/cases/{setup.case}/versions/1/replay", headers=CSRF)
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["match"] is True
    assert (
        body["actual_manifest_hash"]
        == body["expected_manifest_hash"]
        == setup.version.manifest_hash
    )
    app = api.app
    with TestClient(app, base_url="http://127.0.0.1") as viewer:  # type: ignore[arg-type]
        viewer.post(
            "/api/v1/auth/login", json={"username": "vik", "password": PASSWORD}, headers=CSRF
        )
        assert (
            viewer.post(f"/api/v1/cases/{setup.case}/versions/1/replay", headers=CSRF).status_code
            == 403
        )


def test_eval_report_is_404_until_one_exists(setup: Setup, api: TestClient) -> None:
    assert api.get("/api/v1/eval/report").status_code == 404
    assert page_png_path(setup.root / "renders", "a" * 64, 1).name == "p1.png"
