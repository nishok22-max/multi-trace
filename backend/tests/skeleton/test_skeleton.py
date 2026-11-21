"""M2 walking-skeleton tests (IMPLEMENTATION_PLAN D.3, M2).

Every test runs on the synthetic world (always) and on the real downloaded dataset (when present),
so the same assertions guard the real data path.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import (
    CASE_ID,
    REAL_DATASET_PRESENT,
    World,
    build_version,
    real_world,
    synthetic_world,
)
from trace_adapters.pdfium_reader import PdfiumReader
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.main import create_app
from trace_api.settings import load_settings
from trace_core.models.case import CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import SensorWindowPointer, TextSpanPointer
from trace_core.models.time import Interval

CSRF = {"X-TRACE-CSRF": "x"}
KINDS = [
    "synthetic",
    pytest.param(
        "real",
        marks=pytest.mark.skipif(not REAL_DATASET_PRESENT, reason="PdM dataset not downloaded"),
    ),
]


@pytest.fixture(scope="module", params=KINDS)
def world(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> World:
    root = tmp_path_factory.mktemp(f"world-{request.param}")
    return synthetic_world(root) if request.param == "synthetic" else real_world(root)


@pytest.fixture(scope="module")
def version(world: World) -> CaseVersion:
    return build_version(world)


def _claim(version: CaseVersion, label: str) -> ClaimRecord:
    return next(c for c in version.records.claims if c.label == label)


# ------------------------------------------------------------------------------- engine
def test_c17_quote_equals_page_text_slice(world: World, version: CaseVersion) -> None:
    c17 = _claim(version, "C-17")
    ev = c17.evidence
    assert isinstance(ev, TextSpanPointer) and ev.page is not None
    pdf = next(s for s in world.manifest().sources if s.source_id == ev.source_id)
    page = PdfiumReader().page_text(world.ports().blobs.open(pdf.sha256).read(), ev.page - 1)
    assert page.text[ev.char_start : ev.char_end] == ev.quote
    assert hashlib.sha256(ev.quote.encode("utf-8")).hexdigest() == ev.quote_sha256
    assert hashlib.sha256(page.text.encode("utf-8")).hexdigest() == ev.page_text_sha256
    assert page.text.count(ev.quote) == 1 and len(ev.quote) >= 12  # verifier rule 2
    assert (ev.page, ev.line) == (1, 4)
    assert ev.quote.startswith("ran normally")
    assert c17.claim_type == "extracted"
    assert (c17.attribute, c17.value) == ("operating_state", "normal")
    assert c17.unit_status == "not_applicable"
    assert c17.subject.entity_id == "machine:21" and c17.subject.link_status == "resolved"
    vt = c17.temporal.valid_time
    assert isinstance(vt, Interval) and vt.granularity == "day"
    assert (vt.start, vt.end) == ("2015-08-04T18:30:00Z", "2015-08-05T18:30:00Z")  # IST day, in UTC
    assert c17.temporal.observed_time.at == "2015-08-06T03:40:00Z"  # 06 Aug 09:10 IST
    assert c17.temporal.observed_time.basis == "document_date"
    assert c17.confidence.calibrated is False


def test_s88_is_day_level_with_hour_child(version: CaseVersion) -> None:
    s88, child = _claim(version, "S-88"), _claim(version, "S-88.1")
    assert s88.claim_type == "inferred" and s88.unit_status == "sensor_native"
    assert s88.normalized_value is None and s88.normalized_unit is None  # units never converted
    ev = s88.evidence
    assert isinstance(ev, SensorWindowPointer)
    assert (ev.statistic, ev.granularity) == ("robust_max_z", "day")
    vt = s88.temporal.valid_time
    assert isinstance(vt, Interval) and vt.granularity == "day"
    assert ev.n_points == ev.expected_points  # 100% coverage
    env = version.records.envelopes[0]
    assert ev.envelope_id == env.envelope_id and env.envelope_id in s88.derived_from
    windows = [c for c in version.records.claims if c.claim_id in s88.derived_from]
    assert len(windows) == len(env.scope)  # one day-window claim per channel
    assert isinstance(s88.value, dict) and s88.value["state"] == "abnormal"
    assert isinstance(s88.value["T_D"], float) and s88.value["T_star"] == env.T_star
    assert s88.value["T_D"] > env.T_star
    cev = child.evidence
    assert isinstance(cev, SensorWindowPointer) and isinstance(child.temporal.valid_time, Interval)
    assert child.temporal.valid_time.granularity == "hour"
    assert (cev.statistic, cev.granularity) == ("hourly_peak", "hour")
    assert s88.claim_id in child.derived_from  # S-88 lists it as a child
    assert child.claim_type == "inferred" and child.unit_status == "sensor_native"
    assert isinstance(child.value, dict)
    assert child.value["z"] == s88.value["T_D"]  # the peak hour is where T_D is reached
    outside = (
        child.value["reading"] > child.value["band_high"]
        or child.value["reading"] < child.value["band_low"]
    )
    assert outside


def test_gate_records_six_ordered_checks_and_one_conflict(version: CaseVersion) -> None:
    c17, s88 = _claim(version, "C-17"), _claim(version, "S-88")
    pair = [
        c
        for c in version.records.comparisons
        if {c.claim_a, c.claim_b} == {c17.claim_id, s88.claim_id}
    ]
    assert len(pair) == 1 and pair[0].outcome == "disagree"
    assert [c.n for c in pair[0].checks] == [1, 2, 3, 4, 5, 6]
    assert all(c.passed for c in pair[0].checks)
    assert len(version.records.conflicts) == 1
    conflict = version.records.conflicts[0]
    assert sorted(conflict.sides) == sorted([c17.claim_id, s88.claim_id])
    assert conflict.averaged is False
    assert _claim(version, "S-88.1").claim_id in conflict.supporting_context
    assert isinstance(s88.value, dict)
    assert conflict.magnitude.observed == s88.value["T_D"]
    assert conflict.magnitude.threshold == version.records.envelopes[0].T_star


def test_rebuild_same_inputs_same_manifest_hash(
    world: World, version: CaseVersion, tmp_path: Path
) -> None:
    again = build_version(world)
    assert again.manifest_hash == version.manifest_hash and len(version.manifest_hash) == 64
    assert again.parent_manifest_hash is None and again.version == 1
    if "synthetic" in world.data_dir.name:  # an independent world with the same inputs
        other = build_version(synthetic_world(tmp_path))
        assert other.manifest_hash == version.manifest_hash


def test_stored_version_round_trips_and_is_chained(
    world: World, version: CaseVersion, tmp_path: Path
) -> None:
    store = SqliteClaimStore(tmp_path / "chain.db")
    store.commit_build(version, world.manifest())  # ONE transaction
    stored = store.latest(version.case_id)
    assert stored is not None and stored.manifest_hash == version.manifest_hash
    assert store.get_version(version.case_id, 1) == stored
    assert {c.claim_id for c in store.load_claims(version.case_id, 1)} == {
        c.claim_id for c in version.records.claims
    }


# ---------------------------------------------------------------------------------- api
@pytest.fixture
def api(world: World, monkeypatch: pytest.MonkeyPatch, loopback_only: None) -> Iterator[TestClient]:
    monkeypatch.setenv("TRACE_DATA_DIR", str(world.data_dir))
    monkeypatch.setenv("TRACE_DEV_AUTH", "1")
    with TestClient(create_app()) as client:
        yield client


def _wait_done(client: TestClient, build_id: str, timeout_s: float = 240.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(f"/api/v1/cases/{CASE_ID}/builds/{build_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.5)
    raise AssertionError("build did not finish")


def test_skeleton_end_to_end(api: TestClient, world: World) -> None:
    started = api.post(f"/api/v1/cases/{world.case_id}/build", headers=CSRF)
    assert started.status_code == 202
    status = _wait_done(api, started.json()["build_id"])
    assert status["status"] == "done" and status["version"] == 1
    first = api.get(f"/api/v1/cases/{world.case_id}/latest", follow_redirects=False)
    assert first.status_code == 307 and first.headers["cache-control"] == "no-store"
    state = api.get(first.headers["location"]).json()
    manifest_hash = state["manifest_hash"]
    assert len(manifest_hash) == 64
    base = f"/api/v1/cases/{world.case_id}/versions/{state['version']}"
    story = api.get(f"{base}/story").json()
    assert story["headline_outcome"] == "disagree" and len(story["steps"]) == 5
    conflicts = api.get(f"{base}/conflicts").json()["items"]
    comparisons = api.get(f"{base}/comparisons").json()["items"]
    assert len(conflicts) == 1 and conflicts[0]["averaged"] is False
    claims = {c["claim_id"]: c for c in api.get(f"{base}/claims").json()["items"]}
    assert {claims[s]["label"] for s in conflicts[0]["sides"]} == {"C-17", "S-88"}
    cmp_ = next(c for c in comparisons if c["comparison_id"] in conflicts[0]["comparison_ids"])
    assert cmp_["outcome"] == "disagree"
    assert [c["n"] for c in cmp_["checks"]] == [1, 2, 3, 4, 5, 6]  # wire name of passed is "pass"
    assert all(c["pass"] is True for c in cmp_["checks"])
    detail = api.get(f"{base}/claims/{conflicts[0]['sides'][0]}").json()
    assert detail["claim"]["claim_id"] == conflicts[0]["sides"][0]
    # rebuilding the same inputs is idempotent: the same build, the same manifest hash
    again = api.post(f"/api/v1/cases/{world.case_id}/build", headers=CSRF)
    assert again.status_code == 202 and again.json()["build_id"] == started.json()["build_id"]
    assert api.get(f"{base}/state").json()["manifest_hash"] == manifest_hash


def test_versioned_cache_headers_private_immutable(api: TestClient, world: World) -> None:
    started = api.post(f"/api/v1/cases/{world.case_id}/build", headers=CSRF)
    _wait_done(api, started.json()["build_id"])
    url = f"/api/v1/cases/{world.case_id}/versions/1/story"
    res = api.get(url)
    cache = res.headers["cache-control"]
    assert res.status_code == 200
    assert "private" in cache and "max-age=31536000" in cache and "immutable" in cache
    assert "public" not in cache
    assert res.headers["vary"] == "Cookie"
    etag = res.headers["etag"]
    manifest = api.get(f"/api/v1/cases/{world.case_id}/versions/1/manifest").json()
    assert etag == f'"{manifest["manifest_hash"]}"'
    assert api.get(url, headers={"If-None-Match": etag}).status_code == 304
    latest = api.get(f"/api/v1/cases/{world.case_id}/latest", follow_redirects=False)
    assert latest.headers["cache-control"] == "no-store"
    missing = api.get(f"/api/v1/cases/{world.case_id}/versions/99/story")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert api.get("/api/v1/cases/some-other-case/versions/1/story").status_code == 404


# ----------------------------------------------------------------------------- dev auth
def test_dev_auth_off_by_default_returns_401(
    world: World, monkeypatch: pytest.MonkeyPatch, loopback_only: None
) -> None:
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    monkeypatch.setenv("TRACE_DATA_DIR", str(world.data_dir))
    assert load_settings().dev_auth is False
    with TestClient(create_app()) as client:
        for method, path in (
            ("get", f"/api/v1/cases/{world.case_id}/latest"),
            ("get", f"/api/v1/cases/{world.case_id}/versions/1/story"),
            ("get", f"/api/v1/cases/{world.case_id}/versions/1/conflicts"),
            ("post", f"/api/v1/cases/{world.case_id}/build"),
        ):
            res = getattr(client, method)(path, headers=CSRF, follow_redirects=False)
            assert res.status_code == 401, path
            assert res.headers["content-type"].startswith("application/problem+json")
    for value in ("0", "true", "yes", ""):  # only the literal "1" turns it on
        monkeypatch.setenv("TRACE_DEV_AUTH", value)
        assert load_settings().dev_auth is False
