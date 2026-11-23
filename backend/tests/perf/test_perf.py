"""D-13 hot paths (NFR budgets). Serial: run with `make check-perf` (`pytest -m perf`).
Budgets: build < 60 s, decision re-run p95 < 1.5 s (PRD 16 / IMPLEMENTATION_PLAN M3-M4)."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from tests.skeleton.world import build_version, synthetic_world
from tests.unit.engine.test_gate import CFG
from trace_adapters.fakes.clock import FixedClock
from trace_core.rerun import rerun_after_decision

pytestmark = pytest.mark.perf

BUILD_BUDGET_S = 60.0
RERUN_P95_BUDGET_S = 1.5


def test_build_under_budget(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=True)
    started = time.perf_counter()
    version = build_version(world)
    elapsed = time.perf_counter() - started
    assert version.records.claims
    assert elapsed < BUILD_BUDGET_S, f"build took {elapsed:.1f} s"


def test_decision_rerun_p95_under_1500ms(tmp_path: Path) -> None:
    version = build_version(synthetic_world(tmp_path, spike=False))
    samples: list[float] = []
    for i in range(20):
        clock = FixedClock(f"2015-08-06T05:{i:02d}:00Z")
        started = time.perf_counter()
        rerun_after_decision(version, [], CFG, clock)
        samples.append(time.perf_counter() - started)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    assert p95 < RERUN_P95_BUDGET_S, f"p95 {p95:.3f} s (median {statistics.median(samples):.3f} s)"
