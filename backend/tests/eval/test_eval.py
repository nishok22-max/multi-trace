"""D-06/D-07/D-08: injector, protocol and metrics. Named: test_injector_seeded_reproducible,
test_dev_holdout_machines_disjoint, test_wilson_ci_known_values,
test_false_alarm_eval_day_not_in_calibration_set. Holdout-marked tests never run here."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.skeleton.world import CHANNELS, build_version, synthetic_world
from trace_eval.injector import KINDS, draw_faults, plant
from trace_eval.metrics import precision_recall_f1, wilson_ci
from trace_eval.protocol import assert_disjoint, leave_block_out, split_machines

DAYS = [date(2015, 6, 1) + timedelta(days=i) for i in range(60)]
MACHINES = [f"machine:{n}" for n in range(1, 21)]


def test_injector_seeded_reproducible() -> None:
    one = draw_faults(MACHINES, DAYS, CHANNELS, 15, seed=7)
    two = draw_faults(list(reversed(MACHINES)), list(reversed(DAYS)), CHANNELS, 15, seed=7)
    assert one == two  # the input order does not matter, only the seed
    assert draw_faults(MACHINES, DAYS, CHANNELS, 15, seed=8) != one
    assert len({(f.machine, f.day) for f in one}) == 15  # distinct slots
    assert {f.kind for f in one} <= set(KINDS)
    for f in one:
        assert f.hours == tuple(range(f.hours[0], f.hours[0] + len(f.hours)))
        assert (len(f.hours) == 1) == (f.kind == "spike") and max(f.hours) < 24
    with pytest.raises(ValueError):
        draw_faults(MACHINES[:1], DAYS[:2], CHANNELS, 3, seed=1)


def test_planting_changes_only_the_faulted_hours() -> None:
    day = {h: 100.0 + h for h in range(24)}
    faults = draw_faults(MACHINES, DAYS, CHANNELS, 30, seed=3)
    for f in faults:
        out = plant(day, f, centre=100.0, scale=5.0, spreads=15.0)
        touched = {h for h in range(24) if out.get(h) != day[h]}
        assert touched <= set(f.hours)
        if f.kind == "dropout":
            assert all(h not in out for h in f.hours)
        if f.kind == "spike":
            assert out[f.hours[0]] == 100.0 + 15.0 * 5.0


def test_dev_holdout_machines_disjoint() -> None:
    dev, holdout = split_machines(MACHINES, seed=11)
    assert set(dev) | set(holdout) == set(MACHINES) and not set(dev) & set(holdout)
    assert split_machines(MACHINES, seed=11) == (dev, holdout)  # reproducible
    assert split_machines(MACHINES, seed=12) != (dev, holdout)
    with pytest.raises(ValueError):
        assert_disjoint(["machine:1"], ["machine:1", "machine:2"])


def test_wilson_ci_known_values() -> None:
    lo, hi = wilson_ci(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and round(hi, 4) == 0.2775
    lo, hi = wilson_ci(10, 10)
    assert hi == pytest.approx(1.0) and round(lo, 4) == 0.7225
    assert wilson_ci(0, 0) == (0.0, 1.0)  # no data: nothing is known
    lo, hi = wilson_ci(50, 200)
    assert lo < 0.25 < hi and hi - lo < wilson_ci(5, 20)[1] - wilson_ci(5, 20)[0]  # n narrows it
    assert precision_recall_f1(0, 0, 0) == (0.0, 0.0, 0.0)
    assert precision_recall_f1(3, 1, 2) == (0.75, 0.6, pytest.approx(2 * 0.75 * 0.6 / 1.35))


def test_false_alarm_eval_day_not_in_calibration_set(tmp_path: Path) -> None:
    """Quiet-day false alarms are measured leave-block-out: the day under test never helped set
    the threshold it is tested against. The rate stays near the nominal alpha."""
    version = build_version(synthetic_world(tmp_path, spike=False))
    env = version.records.envelopes[0]
    stats = {date.fromisoformat(q.date): q.t_d for q in env.quiet_days}
    alpha = env.params.alpha
    alarms, tested, splits = leave_block_out(stats, alpha, block_days=7)
    assert tested == len(stats) and splits
    for calibration, evaluated in splits:
        assert not set(calibration) & set(evaluated)
    lo, hi = wilson_ci(alarms, tested)
    assert lo <= alpha + 0.1 and alarms / tested <= alpha + 0.1  # conformal bound, with slack
    assert hi >= 0.0
