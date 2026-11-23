"""GET .../integrity re-walks stored bytes and the chain (green/red badge)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.skeleton.world import build_version, synthetic_world
from trace_api.main import create_app


def test_integrity_route_goes_red_when_a_stored_byte_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loopback_only: None
) -> None:
    world = synthetic_world(tmp_path, spike=False)
    version = build_version(world)
    world.store.commit_build(version, world.manifest())
    monkeypatch.setenv("TRACE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRACE_DEV_AUTH", "1")
    url = f"/api/v1/cases/{world.case_id}/versions/1/integrity"
    with TestClient(create_app(), base_url="http://127.0.0.1") as api:
        green = api.get(url)
        assert green.status_code == 200 and green.headers["cache-control"] == "no-store"
        assert green.json()["ok"] is True and green.json()["failures"] == []
        report = next(
            s for s in world.manifest().sources if s.modality == "text" and s.held_reason is None
        )
        blob = tmp_path / "blobs" / report.sha256[:2] / report.sha256
        blob.write_bytes(blob.read_bytes() + b"tampered")
        red = api.get(url).json()
        assert red["ok"] is False and red["records_ok"] is False
        assert any(report.source_id in f for f in red["failures"])
        assert api.get(url.replace("/versions/1/", "/versions/9/")).status_code == 404
