"""The conformal oracle (CLAUDE.md: goldens are blessed only while this is green).

An independent, plain-Python re-implementation of the envelope (PRD 10.3) over the raw Parquet:
no numpy, no engine imports for the statistic, exact `Fraction` arithmetic for the rank. It must
agree with `learn_envelopes` on the quiet days, the per-channel centre and scale, and T*.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from tests.skeleton.world import CASE_DAY, CHANNELS, SERIES, TZ, build_version, synthetic_world
from trace_adapters.telemetry_parquet import series_filename

MARGIN_DAYS = 3
ALPHA = Fraction(5, 100)
SIGMA = 1.4826


def _local_day(ts: str) -> date:
    stamp = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
    return stamp.astimezone(ZoneInfo(TZ)).date()


def _oracle(parquet: Path, event_days: list[date]) -> tuple[list[date], dict[str, float], float]:
    table = pq.read_table(parquet).to_pydict()
    by_day: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for i, ts in enumerate(table["ts"]):
        for channel in CHANNELS:
            by_day[_local_day(ts)][channel].append(table[channel][i])
    avoid = [CASE_DAY, *event_days]
    quiet = sorted(
        d
        for d, chans in by_day.items()
        if all(len(chans[c]) == 24 for c in CHANNELS)
        and all(abs((d - a).days) > MARGIN_DAYS for a in avoid)
    )
    centre: dict[str, float] = {}
    scale: dict[str, float] = {}
    for c in CHANNELS:
        values = [v for d in quiet for v in by_day[d][c]]
        centre[c] = statistics.median(values)
        scale[c] = SIGMA * statistics.median([abs(v - centre[c]) for v in values])
    day_stat = sorted(
        max(abs(v - centre[c]) / scale[c] for c in CHANNELS for v in by_day[d][c]) for d in quiet
    )
    n = len(quiet)
    k = math.ceil((1 - ALPHA) * (n + 1))
    return quiet, centre, day_stat[k - 1]


def test_conformal_oracle(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=False)
    version = build_version(world)
    env = version.records.envelopes[0]
    # the synthetic event rows (see the world) as plant-local dates
    events = [date(2015, 7, 10), date(2015, 9, 1), date(2015, 6, 15)]
    quiet, centre, t_star = _oracle(tmp_path / "derived" / series_filename(SERIES), events)
    assert [q.date for q in env.quiet_days] == [d.isoformat() for d in quiet]
    assert env.n == len(quiet) and env.pooled == "none"
    for channel in CHANNELS:
        assert env.med[channel] == centre[channel]
    assert math.isclose(env.T_star, t_star, rel_tol=1e-12)
    # the rank is the documented one, exactly: k = ceil((1 - alpha)(n + 1))
    k = math.ceil((1 - ALPHA) * (env.n + 1))
    ranked = sorted(q.t_d for q in env.quiet_days)
    assert env.T_star == ranked[k - 1]
    assert timedelta(days=MARGIN_DAYS).days == MARGIN_DAYS
