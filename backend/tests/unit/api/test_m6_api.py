"""M6 API behaviour: the anchor flag on the integrity answer, and the evaluation report being the
holdout once it exists and showing as superseded when the engine changed. Named:
test_roots_visible_in_the_ui (API half), test_report_superseded_on_engine_change (API half)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import build_version, synthetic_world
from tests.unit.api.test_auth import CSRF, PASSWORD
from trace_adapters.fakes.clock import FixedClock
from trace_api import deps
from trace_api.main import create_app
from trace_api.security.sessions import AuthRepository
from trace_eval.runner import run_dev
from trace_worker.env import engine_sha


@pytest.fixture
def api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None
) -> Iterator[tuple[TestClient, Path, str]]:
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRACE_ANCHORS", str(tmp_path / "anchors.txt"))
    monkeypatch.delenv("TRACE_DEV_AUTH", raising=False)
    world = synthetic_world(tmp_path, spike=True)
    version = build_version(world)
    world.store.commit_build(version, world.manifest())
    repo = AuthRepository(tmp_path / "trace.db", FixedClock("2015-08-06T05:00:00Z"))
    repo.create_user("u-eve", "eve", "Eve", "evaluator", PASSWORD)
    app = create_app()
    app.dependency_overrides[deps.get_auth_repo] = lambda: repo
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post(
            "/api/v1/auth/login", json={"username": "eve", "password": PASSWORD}, headers=CSRF
        )
        yield client, tmp_path, version.manifest_hash


def test_roots_visible_in_the_ui_flag_follows_the_anchor_file(
    api: tuple[TestClient, Path, str],
) -> None:
    client, root, manifest = api
    case = next(iter(root.glob("derived")), None) and "case-m21-2015-08-05"
    url = f"/api/v1/cases/{case}/versions/1/integrity"
    first = client.get(url)
    assert first.status_code == 200 and first.headers["x-manifest-anchored"] == "false"
    (root / "anchors.txt").write_text(
        f"# header\n2015-08-06T04:00:00Z {case} v1 {manifest}\n", encoding="utf-8"
    )
    again = client.get(url)
    assert again.headers["x-manifest-anchored"] == "true"  # no-store answer: it follows the file
    assert again.headers["cache-control"] == "no-store"


def test_the_holdout_report_wins_and_a_changed_engine_is_flagged(
    api: tuple[TestClient, Path, str],
) -> None:
    client, root, _ = api
    run_dev(root / "eval_report.json", n_per_kind=1, seed=3)
    dev = client.get("/api/v1/eval/report")
    assert dev.status_code == 200 and dev.json()["split"] == "dev"
    assert dev.headers["x-report-superseded"] == "false"  # made by the engine running now
    holdout = json.loads((root / "eval_report.json").read_text(encoding="utf-8"))
    holdout.update(split="holdout", engine_sha="f" * 64, run_id="holdout-test")
    (root / "eval_report_holdout.json").write_text(json.dumps(holdout), encoding="utf-8")
    got = client.get("/api/v1/eval/report")
    assert got.json()["split"] == "holdout"  # a later dev run never replaces it
    assert got.headers["x-report-superseded"] == "true"  # another engine than HEAD made it
    assert engine_sha() != "f" * 64
