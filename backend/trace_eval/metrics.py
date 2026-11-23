"""Metrics with confidence intervals (D-08). Rates are reported with Wilson 95% intervals, so a
small n is visibly uncertain; calibration is reported with ECE and Brier plus seeded bootstrap
intervals and per-bin counts. Nothing is rounded before it is shown."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Z_95 = 1.959963984540054
BINS = 10


def wilson_ci(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials. (0, 1) when n = 0 (nothing known)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Undefined ratios are 0.0 (no claims made / no truth present), never 1.0."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


@dataclass(frozen=True)
class BinStat:
    lo: float
    hi: float
    n: int
    accuracy: float | None
    mean_confidence: float | None


def calibration_bins(
    confidence: Sequence[float], correct: Sequence[bool], bins: int = BINS
) -> list[BinStat]:
    """Equal-width bins on [0, 1]; the last bin includes 1.0. Empty bins keep their count (0)
    and have no accuracy: they are reported, never filled in."""
    if len(confidence) != len(correct):
        raise ValueError("confidence and correctness must have the same length")
    members: list[list[int]] = [[] for _ in range(bins)]
    for i, c in enumerate(confidence):
        if not 0.0 <= c <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")
        members[min(bins - 1, int(c * bins))].append(i)
    out: list[BinStat] = []
    for b, idx in enumerate(members):
        if not idx:
            out.append(BinStat(b / bins, (b + 1) / bins, 0, None, None))
            continue
        acc = sum(1 for i in idx if correct[i]) / len(idx)
        conf = sum(confidence[i] for i in idx) / len(idx)
        out.append(BinStat(b / bins, (b + 1) / bins, len(idx), acc, conf))
    return out


def ece(confidence: Sequence[float], correct: Sequence[bool], bins: int = BINS) -> float:
    """Expected calibration error: bin-weighted |accuracy - mean confidence|; empty bins add 0."""
    n = len(confidence)
    if n == 0:
        return 0.0
    total = 0.0
    for b in calibration_bins(confidence, correct, bins):
        if b.n and b.accuracy is not None and b.mean_confidence is not None:
            total += b.n / n * abs(b.accuracy - b.mean_confidence)
    return total


def brier(confidence: Sequence[float], correct: Sequence[bool]) -> float:
    """Mean squared difference between the stated probability and the 0/1 outcome."""
    if len(confidence) != len(correct):
        raise ValueError("confidence and correctness must have the same length")
    if not confidence:
        return 0.0
    return sum(
        (c - (1.0 if y else 0.0)) ** 2 for c, y in zip(confidence, correct, strict=True)
    ) / len(confidence)


def bootstrap_ci(
    statistic: Callable[[Sequence[int]], float],
    n: int,
    *,
    resamples: int = 1000,
    seed: int = 0,
    level: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap of `statistic` over index resamples of range(n). The generator is
    seeded, so the interval is reproducible; the point estimate is the caller's own value."""
    if n <= 0:
        return 0.0, 1.0
    rng = random.Random(seed)  # noqa: S311 (reproducible resampling, not security)
    draws = sorted(statistic([rng.randrange(n) for _ in range(n)]) for _ in range(resamples))
    lo = draws[int((1 - level) / 2 * (resamples - 1))]
    hi = draws[int((1 + level) / 2 * (resamples - 1))]
    return lo, hi
