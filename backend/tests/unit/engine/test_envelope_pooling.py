"""B-03: thin-history pooling. Named: test_thin_history_uses_model_pool, plus the fail-closed case
and the conformal rank of the pooled quantile."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.unit.engine.test_gaps import CFG
from trace_adapters.telemetry_parquet import ParquetTelemetryReader, series_filename
from trace_core.errors import ThinHistoryError
from trace_core.models.case import Case
from trace_core.normalise.envelopes import conformal_rank, learn_envelopes
from trace_core.normalise.time import hours_in, local_day_bounds
from trace_core.read.sensor import telemetry_series_id

TZ = CFG.case.plant_tz
CHANNELS = ("pressure", "rotate", "vibration", "volt")
CASE = Case(
    case_id="case-pool",
    title="pool",
    entities=["machine:21"],
    window_start=local_day_bounds(date(2015, 8, 5), TZ)[0],
    window_end=local_day_bounds(date(2015, 8, 5), TZ)[1],
    plant_tz=TZ,
    created_at="2015-08-06T04:00:00Z",
)


def _write(root: Path, entity: str, first: date, last: date, seed: int) -> None:
    rng = np.random.default_rng(seed)
    rows: dict[str, list[object]] = {"ts": [], **{c: [] for c in CHANNELS}}
    day = first
    while day <= last:
        for ts in hours_in(*local_day_bounds(day, TZ)):
            rows["ts"].append(ts)
            for c in CHANNELS:
                rows[c].append(100.0 + 10.0 * float(rng.standard_normal()))
        day += timedelta(days=1)
    pq.write_table(pa.table(rows), root / series_filename(telemetry_series_id(entity)))


def _learn(root: Path, peers: dict[str, list[str]] | None):  # type: ignore[no-untyped-def]
    return learn_envelopes(
        ParquetTelemetryReader(root), [], [], CASE, CFG_ONTOLOGY, CFG, model_peers=peers
    )


CFG_ONTOLOGY = CFG.ontology


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _write(tmp_path, "machine:22", date(2015, 6, 1), date(2015, 8, 31), 22)
    _write(tmp_path, "machine:23", date(2015, 6, 1), date(2015, 8, 31), 23)
    return tmp_path


def test_thin_history_uses_model_pool(root: Path) -> None:
    """17 quiet days (< 19, >= 10): T* is pooled over the model; med/MAD stay the machine's own."""
    _write(root, "machine:21", date(2015, 7, 20), date(2015, 8, 12), 21)
    (env,) = _learn(root, {"machine:21": ["machine:22", "machine:23", "machine:21"]})
    assert CFG.envelope.min_quiet_days_own_scale <= env.n < CFG.envelope.min_quiet_days_own_t_star
    assert env.pooled == "t_star_model" and env.pool_members == ["machine:22", "machine:23"]
    pooled_days = [q.t_d for q in env.quiet_days]
    assert len(pooled_days) == env.n  # the machine's own days are the ones shown
    assert env.T_star > 0


def test_very_thin_history_pools_scale_too(root: Path) -> None:
    _write(root, "machine:21", date(2015, 7, 28), date(2015, 8, 9), 21)
    (env,) = _learn(root, {"machine:21": ["machine:22", "machine:23"]})
    assert env.n < CFG.envelope.min_quiet_days_own_scale
    assert env.pooled == "model_level"
    # the model-level centre is the pooled median, close to the generating centre
    assert all(abs(m - 100.0) < 5.0 for m in env.med.values())


def test_pooled_quantile_follows_the_conformal_rank(root: Path) -> None:
    _write(root, "machine:21", date(2015, 7, 20), date(2015, 8, 12), 21)
    (env,) = _learn(root, {"machine:21": ["machine:22", "machine:23"]})
    reader = ParquetTelemetryReader(root)
    assert reader.partition_sha(env.series_id) == env.partition_hashes[env.series_id]
    pooled_n = env.n + 2 * len(_quiet_days_of(root, "machine:22"))
    assert conformal_rank(pooled_n, CFG.envelope.alpha) <= pooled_n


def _quiet_days_of(root: Path, entity: str) -> list[date]:
    from trace_core.normalise.envelopes import _prepare  # internal: counted, not re-derived
    from trace_core.normalise.time import days_between

    machine = _prepare(
        ParquetTelemetryReader(root),
        [],
        days_between(CASE.window_start, CASE.window_end, TZ),
        CFG,
        entity,
    )
    return machine.quiet


def test_thin_history_without_peers_fails_closed(root: Path) -> None:
    _write(root, "machine:21", date(2015, 7, 20), date(2015, 8, 12), 21)
    with pytest.raises(ThinHistoryError):
        _learn(root, None)
    with pytest.raises(ThinHistoryError):
        _learn(root, {"machine:21": ["machine:99"]})  # a peer without telemetry cannot help


def test_a_machine_with_enough_history_is_not_pooled(root: Path) -> None:
    _write(root, "machine:21", date(2015, 6, 1), date(2015, 8, 31), 21)
    env, *scoped = _learn(root, {"machine:21": ["machine:22"]})
    assert env.pooled == "none" and env.pool_members == []
    assert sorted(e.scope[0] for e in scoped) == [
        "pressure",
        "rotate",
        "vibration",
    ]  # per-phrase scopes
    assert all(len(e.scope) == 1 and e.pooled == "none" for e in scoped)
