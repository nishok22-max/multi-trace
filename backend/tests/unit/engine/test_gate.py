"""B-08: the gate over a calm synthetic day. Named: test_forall_normal_vs_error_row_disagrees,
test_forall_agree_requires_log_coverage_of_window, test_conflict_grouping_events_as_context,
prop_gate_totality, prop_gate_symmetry, prop_never_average."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_gaps import _event
from trace_adapters.config_loader import load_config_bundle
from trace_core.compare.conflicts import group_conflicts
from trace_core.compare.gate import gate
from trace_core.ids import config_hash
from trace_core.models.case import CaseVersion
from trace_core.models.claims import ClaimRecord
from trace_core.models.records import CoveragePeriod
from trace_core.models.time import Interval
from trace_core.stage_types import GateContext

CFG = load_config_bundle()
COVER = CoveragePeriod(start="2015-01-01T00:00:00Z", end="2016-01-01T00:00:00Z")
OUTCOMES = {"agree", "disagree", "cant_compare", "cant_tell"}


@pytest.fixture(scope="module")
def calm(tmp_path_factory: pytest.TempPathFactory) -> tuple[World, CaseVersion]:
    world = synthetic_world(tmp_path_factory.mktemp("calm"), spike=False)
    return world, build_version(world)


def _pair(version: CaseVersion) -> tuple[ClaimRecord, ClaimRecord]:
    cmp_ = version.records.comparisons[0]
    by_id = {c.claim_id: c for c in version.records.claims}
    return by_id[cmp_.claim_a], by_id[cmp_.claim_b]


def _ctx(
    version: CaseVersion, events: list[ClaimRecord], coverage: list[CoveragePeriod]
) -> GateContext:
    return GateContext(
        config=CFG,
        config_hash=config_hash(CFG),
        envelopes=version.records.envelopes,
        events=events,
        log_coverage=coverage,
    )


def _window_hour(a: ClaimRecord, b: ClaimRecord) -> str:
    for c in (a, b):
        vt = c.temporal.valid_time
        if c.modality == "text" and isinstance(vt, Interval):
            return vt.start
    raise AssertionError("no text interval")


def test_calm_day_with_declared_log_coverage_agrees(calm: tuple[World, CaseVersion]) -> None:
    _, version = calm
    assert version.records.comparisons[0].outcome == "agree"
    a, b = _pair(version)
    assert gate(a, b, _ctx(version, [], [COVER])).outcome == "agree"


def test_forall_normal_vs_error_row_disagrees(calm: tuple[World, CaseVersion]) -> None:
    _, version = calm
    a, b = _pair(calm[1])
    error = _event("error_event", _window_hour(a, b))
    record = gate(a, b, _ctx(version, [error], [COVER]))
    assert record.outcome == "disagree"
    assert "event(s) logged" in record.reason and record.checks[-1].passed


def test_forall_agree_requires_log_coverage_of_window(calm: tuple[World, CaseVersion]) -> None:
    _, version = calm
    a, b = _pair(version)
    none = gate(a, b, _ctx(version, [], []))
    assert none.outcome == "cant_tell" and not none.checks[-1].passed
    short = CoveragePeriod(start="2015-08-05T00:00:00Z", end="2015-08-05T06:00:00Z")
    assert gate(a, b, _ctx(version, [], [short])).outcome == "cant_tell"


def test_conflict_grouping_events_as_context(calm: tuple[World, CaseVersion]) -> None:
    _, version = calm
    a, b = _pair(version)
    error = _event("error_event", _window_hour(a, b))
    record = gate(a, b, _ctx(version, [error], [COVER]))
    (conflict,) = group_conflicts([record], [a, b, error])
    assert conflict.supporting_context == [error.claim_id]
    assert conflict.averaged is False and sorted(conflict.sides) == sorted([a.claim_id, b.claim_id])


@given(
    n_events=st.integers(min_value=0, max_value=2),
    covered=st.booleans(),
)
def test_prop_gate_totality_and_symmetry(n_events: int, covered: bool) -> None:
    """Every ordered pair gets exactly one outcome from the closed set, and swapping the sides
    changes nothing but the order of the claim ids."""
    world_version = _CALM[0]
    a, b = _pair(world_version)
    events = [_event("error_event", _window_hour(a, b)) for _ in range(n_events)]
    ctx = _ctx(world_version, events, [COVER] if covered else [])
    forward, backward = gate(a, b, ctx), gate(b, a, ctx)
    assert forward.outcome in OUTCOMES and backward.outcome in OUTCOMES
    assert forward.outcome == backward.outcome and forward.reason == backward.reason
    assert forward.comparison_id == backward.comparison_id  # claim ids are sorted into the id
    if n_events:
        assert forward.outcome == "disagree"  # an event is never averaged away


_CALM: list[CaseVersion] = []


@pytest.fixture(scope="module", autouse=True)
def _remember(calm: tuple[World, CaseVersion]) -> None:
    _CALM[:] = [calm[1]]


def test_prop_never_average(calm: tuple[World, CaseVersion]) -> None:
    _, version = calm
    assert all(c.averaged is False for c in version.records.conflicts)
    assert all(c.outcome in OUTCOMES for c in version.records.comparisons)
