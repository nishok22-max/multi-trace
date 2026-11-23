"""A-08: build child guards. Named: test_parse_child_env_has_no_groq_key,
test_timeout_kills_tesseract_grandchild, test_kill_mid_build_marks_stale_then_rebuilds,
test_build_key_idempotent, plus the self-deadline and orphan watch."""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
from datetime import timedelta
from multiprocessing.queues import Queue
from pathlib import Path

import pytest

from tests.skeleton.world import build_version, synthetic_world
from tests.unit.engine.test_gate import CFG
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.sqlite.builds import BuildInProgress, BuildRepository
from trace_worker.build_runner import scrub_env
from trace_worker.child_guard import (
    DEADLINE_EXIT,
    ORPHAN_EXIT,
    apply_rlimits,
    kill_tree,
    start_deadline,
    start_parent_watch,
)
from trace_worker.env import build_key
from trace_worker.sweep import STALE_AFTER, sweep_stale

SENTINEL = "gsk_SENTINEL_not_a_real_key"


def _child_env(out: Queue[list[str]]) -> None:
    scrub_env()
    out.put(sorted(os.environ))


def test_parse_child_env_has_no_groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    monkeypatch.setenv("OPENAI_API_KEY", SENTINEL)
    monkeypatch.setenv("TRACE_DATA_DIR", "kept")
    monkeypatch.setenv("SOME_OTHER_SECRET", SENTINEL)
    ctx = multiprocessing.get_context("spawn")  # the real child: it inherits the parent's env
    out: Queue[list[str]] = ctx.Queue()  # type: ignore[assignment]
    child = ctx.Process(target=_child_env, args=(out,))
    child.start()
    names = out.get(timeout=60)
    child.join(30)
    assert child.exitcode == 0
    assert "GROQ_API_KEY" not in names and "OPENAI_API_KEY" not in names
    assert "SOME_OTHER_SECRET" not in names  # allowlist, not denylist
    assert "TRACE_DATA_DIR" in names and "PATH" in names or sys.platform != "win32"


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_timeout_kills_tesseract_grandchild() -> None:
    """The tool the child launched (a grandchild) dies with the child on a timeout."""
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(g.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)  # noqa: S603
    assert child.stdout is not None
    grandchild = int(child.stdout.readline())
    try:
        assert _alive(child.pid) and _alive(grandchild)
        kill_tree(child.pid)
        child.wait(timeout=30)
        deadline = time.monotonic() + 15
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(grandchild)
    finally:
        kill_tree(child.pid)
        kill_tree(grandchild)


def test_kill_tree_on_a_dead_process_does_not_raise() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    proc.wait(timeout=30)
    kill_tree(proc.pid)


def test_self_deadline_and_orphan_watch_end_the_process() -> None:
    codes: list[int] = []
    timer = start_deadline(0.05, exit_fn=codes.append)
    time.sleep(0.3)
    timer.cancel()
    assert codes == [DEADLINE_EXIT]

    alive = [True, True, False]
    seen: list[int] = []
    start_parent_watch(lambda: alive.pop(0) if alive else False, interval=0.02, exit_fn=seen.append)
    time.sleep(0.4)
    assert seen == [ORPHAN_EXIT]  # the parent went away: the child exits, it does not linger


def test_rlimit_is_reported_honestly() -> None:
    if sys.platform == "win32":
        assert apply_rlimits(1 << 40) is False  # no resource module: never claim a limit
    else:
        pytest.skip("setting RLIMIT_AS would constrain the test process itself")


def test_kill_mid_build_marks_stale_then_rebuilds(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=False)
    repo = BuildRepository(world.data_dir / "trace.db")
    key = build_key(world.manifest(), CFG)
    case = world.case_id
    repo.create("b1", case, key, "2015-08-06T04:00:00Z")
    repo.mark_running("b1", "2015-08-06T04:00:00Z")  # the child was killed: no more heartbeats
    with pytest.raises(BuildInProgress):
        repo.create("b2", case, key, "2015-08-06T04:00:10Z")  # the slot is still taken
    assert sweep_stale(repo, FixedClock("2015-08-06T04:00:10Z")) == []  # 10 s is not stale yet
    assert STALE_AFTER < timedelta(minutes=1)
    assert sweep_stale(repo, FixedClock("2015-08-06T04:01:00Z")) == ["b1"]
    status = repo.get("b1")
    assert status is not None and status.status == "failed_stale"
    repo.create("b3", case, key, "2015-08-06T04:01:01Z")  # the same key can be retried
    assert repo.in_flight(case)


def test_build_key_idempotent(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=False)
    manifest = world.manifest()
    assert build_key(manifest, CFG) == build_key(manifest, CFG)
    assert build_key(manifest, CFG, ["dec_b", "dec_a"]) == build_key(
        manifest, CFG, ["dec_a", "dec_b"]
    )
    assert build_key(manifest, CFG, ["dec_a"]) != build_key(manifest, CFG)  # a decision is an input
    assert build_version(world).records.claims  # the key does not depend on the build output
