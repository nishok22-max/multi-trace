"""Cross-team (M5): `test_network_off_build_succeeds`: a full build in the real build child with
every socket call made to fail (the analogue of `--network none`). P0 code makes zero network calls
(CLAUDE.md), and this proves it for the build path."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from tests.skeleton.world import synthetic_world
from tests.unit.engine.test_gate import CFG
from trace_adapters.sqlite.builds import BuildRepository
from trace_worker.build_runner import BuildPaths
from trace_worker.env import build_key


def offline_build(paths: BuildPaths, case_id: str, build_id: str) -> None:
    """Spawn target: sockets raise, then the normal build runs."""
    import socket

    def blocked(*args: object, **kwargs: object) -> object:
        raise OSError("network is off")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyaddr"):
        setattr(socket, name, blocked)
    try:
        socket.socket()
    except OSError:
        pass
    else:  # the guard itself must hold, or the test proves nothing
        raise SystemExit(3)
    from trace_worker.build_runner import run_build

    run_build(paths, case_id, build_id)


def test_network_off_build_succeeds(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=True)
    repo = BuildRepository(tmp_path / "trace.db")
    key = build_key(world.manifest(), CFG)
    repo.create("bld_offline", world.case_id, key, "2015-08-06T04:00:00Z")
    paths = BuildPaths(
        db=str(tmp_path / "trace.db"),
        blobs=str(tmp_path / "blobs"),
        derived=str(tmp_path / "derived"),
        renders=str(tmp_path / "renders"),
    )
    child = multiprocessing.get_context("spawn").Process(
        target=offline_build, args=(paths, world.case_id, "bld_offline")
    )
    child.start()
    child.join(240)
    assert child.exitcode == 0, f"child exit code {child.exitcode}"
    status = repo.get("bld_offline")
    assert status is not None and status.status == "done" and status.version == 1
    version = world.store.latest(world.case_id)
    assert version is not None and version.records.comparisons[0].outcome == "disagree"
    assert any((tmp_path / "renders").rglob("p1.png"))  # the page render needed no network either


def test_the_guard_really_blocks_sockets() -> None:
    child = multiprocessing.get_context("spawn").Process(
        target=_check_guard,
    )
    child.start()
    child.join(60)
    assert child.exitcode == 0


def _check_guard() -> None:
    import socket

    def blocked(*args: object, **kwargs: object) -> object:
        raise OSError("network is off")

    socket.socket = blocked  # type: ignore[assignment,misc]
    with pytest.raises(OSError):
        socket.socket()
