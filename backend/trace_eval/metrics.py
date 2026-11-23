"""Metrics with confidence intervals (D-08). Rates are reported with Wilson 95% intervals, so a
small n is visibly uncertain; nothing is rounded before it is shown."""

from __future__ import annotations

import math

Z_95 = 1.959963984540054


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
