"""Numbers are computed, never typed (promise 8) and the engine never averages or guesses
(promises 1, 4): independent recomputation, literal scan, partial coverage, duplicates."""

from __future__ import annotations

import ast
import io
import math
import re
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from tests.skeleton.world import (
    CASE_DAY,
    CHANNELS,
    REAL_DATASET_PRESENT,
    SERIES,
    TZ,
    World,
    build_version,
    real_world,
    synthetic_world,
)
from tools import check_no_mean
from trace_adapters.telemetry_parquet import series_filename
from trace_core.models.case import CaseVersion

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
DEMO_INTS = {64, 34, 47}
DEMO_FLOATS = {0.71, 0.94, 0.62, 0.22}
KINDS = [
    "synthetic",
    pytest.param(
        "real",
        marks=pytest.mark.skipif(not REAL_DATASET_PRESENT, reason="PdM dataset not downloaded"),
    ),
]


@pytest.fixture(scope="module", params=KINDS)
def world(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> World:
    root = tmp_path_factory.mktemp(f"nworld-{request.param}")
    return synthetic_world(root) if request.param == "synthetic" else real_world(root)


def _event_days(world: World) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    for src in world.manifest().sources:
        if src.modality == "table" and src.held_reason is None:
            frame = pd.read_csv(io.BytesIO(world.ports().blobs.open(src.sha256).read()))
            out.extend(pd.to_datetime(frame["datetime"]).dt.normalize())
    return out


def independent_numbers(world: World) -> dict[str, float]:
    """The PRD 10.3 procedure again, in pandas, without touching trace_core."""
    frame = pq.read_table(world.data_dir / "derived" / series_filename(SERIES)).to_pandas()
    local = pd.to_datetime(frame["ts"], utc=True).dt.tz_convert(TZ).dt.tz_localize(None)
    frame = frame.assign(day=local.dt.normalize())
    case_day = pd.Timestamp(CASE_DAY)
    margin = pd.Timedelta(days=3)
    full = set(
        frame.groupby("day")[list(CHANNELS)].count().eq(24).all(axis=1).loc[lambda s: s].index
    )
    events = _event_days(world)
    quiet = sorted(
        d for d in full if abs(d - case_day) > margin and all(abs(d - e) > margin for e in events)
    )
    rows = frame[frame["day"].isin(quiet)]
    med = rows[list(CHANNELS)].median()
    mad = (rows[list(CHANNELS)] - med).abs().median()
    z = (frame[list(CHANNELS)] - med).abs() / (1.4826 * mad)
    frame = frame.assign(z=z.max(axis=1))
    per_day = frame.groupby("day")["z"].max()
    n = len(quiet)
    k = math.ceil(Fraction(95, 100) * (n + 1))
    peak_row = frame[frame["day"] == case_day].sort_values("z").iloc[-1]
    return {
        "n": float(n),
        "t_star": float(sorted(per_day.loc[quiet])[k - 1]),
        "t_d": float(per_day.loc[case_day]),
        "peak_vibration": float(peak_row["vibration"]),
    }


def test_skeleton_numbers_computed_not_literal(world: World) -> None:
    version = build_version(world)
    env = version.records.envelopes[0]
    mine = independent_numbers(world)
    s88 = next(c for c in version.records.claims if c.label == "S-88")
    child = next(c for c in version.records.claims if c.label == "S-88.1")
    assert isinstance(s88.value, dict) and isinstance(child.value, dict)
    assert env.n == int(mine["n"])
    assert env.T_star == pytest.approx(mine["t_star"], rel=1e-12)
    assert s88.value["T_D"] == pytest.approx(mine["t_d"], rel=1e-12)
    assert child.value["reading"] == pytest.approx(mine["peak_vibration"], rel=1e-12)
    # every number a person reads comes from those engine values, formatted
    shown = " ".join(
        [s.text for s in version.views.story.steps]
        + [c.detail for cmp_ in version.records.comparisons for c in cmp_.checks]
        + [c.reason for c in version.records.comparisons]
        + [s88.statement, child.statement]
    )
    assert f"{s88.value['T_D']:.2f}" in shown and f"{env.T_star:.2f}" in shown
    assert f"{child.value['reading']:.2f}" in shown
    # the conformal rank is the documented one
    ranked = sorted(q.t_d for q in env.quiet_days)
    assert env.T_star == ranked[math.ceil(Fraction(95, 100) * (env.n + 1)) - 1]
    assert env.pooled == "none" and env.degenerate_channels == []


def _literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):  # `"0" * 64` is a hash length, not a demo number
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    skip.update(id(n) for n in (node.left, node.right))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in skip:
            value = node.value
            if (isinstance(value, bool) or not isinstance(value, int | float)) or not (
                value in DEMO_INTS or value in DEMO_FLOATS
            ):
                continue
            hits.append(f"{path.relative_to(BACKEND).as_posix()}:{node.lineno}: {value!r}")
    return hits


def test_no_demo_literals_in_engine_api_or_ui_code() -> None:
    hits: list[str] = []
    for package in ("trace_core", "trace_api", "trace_worker"):  # adapters hold byte sizes
        for path in sorted((BACKEND / package).rglob("*.py")):
            hits.extend(_literals(path))
    assert hits == [], hits
    pattern = re.compile(r"(?<![\w.])(64|34|47|0\.71|0\.94|0\.62|0\.22)(?![\w.])")
    ui: list[str] = []
    for path in sorted((REPO / "frontend" / "src").rglob("*")):
        if path.suffix in {".ts", ".tsx", ".astro"} and path.name != "schema.d.ts":
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    ui.append(f"{path.name}:{number}: {line.strip()}")
    assert ui == [], ui
    assert check_no_mean.scan() == []  # tools/check_no_mean stays clean


# ----------------------------------------------------------- promises 1 and 4, end to end
def _outcome(version: CaseVersion) -> tuple[str, str]:
    cmp_ = version.records.comparisons[0]
    return cmp_.outcome, cmp_.reason


def test_forall_agrees_only_with_full_coverage_and_partial_is_cant_tell(tmp_path: Path) -> None:
    calm = build_version(synthetic_world(tmp_path / "calm", spike=False))
    assert _outcome(calm)[0] == "agree"  # 100% coverage, inside the band
    partial = build_version(synthetic_world(tmp_path / "partial", spike=False, drop_hours=(3, 4)))
    outcome, reason = _outcome(partial)
    assert (
        outcome == "cant_tell" and "8 of 96 readings missing" in reason
    )  # no data is never normal
    gaps = [c for c in partial.records.claims if c.attribute == "data_availability"]
    assert gaps and all(g.value == "missing" and g.claim_type == "inferred" for g in gaps)
    assert set(partial.views.state.gap_claim_ids) == {g.claim_id for g in gaps}


def test_violation_in_available_hours_still_disagrees_with_partial_coverage(tmp_path: Path) -> None:
    version = build_version(synthetic_world(tmp_path / "w", spike=True, drop_hours=(3,)))
    assert _outcome(version)[0] == "disagree"  # a violation is a violation, conservatively


def test_duplicate_timestamps_become_a_gap_never_a_mean(tmp_path: Path) -> None:
    version = build_version(synthetic_world(tmp_path / "w", spike=False, duplicate_hour=9))
    gaps = [
        c
        for c in version.records.claims
        if c.attribute == "data_availability" and c.value == "conflicting_readings"
    ]
    assert len(gaps) == len(CHANNELS)  # one per channel, never merged
    window = next(
        c
        for c in version.records.claims
        if c.attribute == "vibration" and c.modality == "sensor" and c.claim_type == "extracted"
    )
    assert isinstance(window.value, dict) and len(window.value) == 23  # the 24th is not guessed
    assert _outcome(version)[0] == "cant_tell"


def test_event_days_are_excluded_from_quiet_days(world: World) -> None:
    version = build_version(world)
    env = version.records.envelopes[0]
    quiet = {date.fromisoformat(q.date) for q in env.quiet_days}
    events = {
        d.date()
        for c in version.records.claims
        if c.attribute in {"error_event", "maintenance_action", "failure_event"}
        for d in [pd.Timestamp(c.temporal.valid_time.start).tz_convert(TZ).tz_localize(None)]  # type: ignore[union-attr]
    }
    assert events, "the world must contain event rows"
    for event in events:
        assert not any(abs(day - event) <= timedelta(days=3) for day in quiet)
    assert not any(abs(day - CASE_DAY) <= timedelta(days=3) for day in quiet)
    assert np.isfinite(env.T_star)
