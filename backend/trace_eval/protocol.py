"""Evaluation protocol (D-07): dev and holdout machines are disjoint, and a quiet day is never
evaluated against an envelope it helped calibrate (leave-block-out)."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal


def split_machines(
    machines: Sequence[str], seed: int, dev_fraction: Decimal = Decimal("0.6")
) -> tuple[list[str], list[str]]:
    """Deterministic dev/holdout split by machine (never by day)."""
    ordered = sorted(set(machines))
    random.Random(seed).shuffle(ordered)  # noqa: S311 (reproducible split, not security)
    cut = int((Decimal(len(ordered)) * dev_fraction).to_integral_value())
    dev, holdout = sorted(ordered[:cut]), sorted(ordered[cut:])
    assert_disjoint(dev, holdout)
    return dev, holdout


def assert_disjoint(dev: Sequence[str], holdout: Sequence[str]) -> None:
    overlap = set(dev) & set(holdout)
    if overlap:
        raise ValueError("a machine is in both dev and holdout")


def leave_block_out(
    statistics: Mapping[date, float], alpha: float, block_days: int
) -> tuple[int, int, list[tuple[list[date], list[date]]]]:
    """For each block of `block_days` consecutive quiet days, calibrate T* on the days OUTSIDE the
    block (conformal rank) and count false alarms inside it. Returns (alarms, tested, splits) where
    each split is (calibration days, evaluated days): the two never overlap."""
    days = sorted(statistics)
    alarms = tested = 0
    splits: list[tuple[list[date], list[date]]] = []
    for start in range(0, len(days), block_days):
        block = days[start : start + block_days]
        rest = [d for d in days if d not in block]
        if not rest:
            continue
        ranked = sorted(statistics[d] for d in rest)
        k = min(len(ranked), math.ceil((1 - alpha) * (len(ranked) + 1)))
        t_star = ranked[k - 1]
        alarms += sum(1 for d in block if statistics[d] > t_star)
        tested += len(block)
        splits.append((rest, block))
    return alarms, tested, splits
