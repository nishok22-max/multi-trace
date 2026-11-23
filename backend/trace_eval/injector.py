"""Seeded fault injector (D-06): faults are PLANTED, so the truth is known without labelling.

Everything is driven by `random.Random(seed)` (never the hash seed or the clock), so the same seed
gives the same faults on every machine. Planting never averages or smooths: a spike overwrites one
reading, a dropout deletes readings, a flatline repeats one reading.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

FaultKind = Literal["spike", "dropout", "flatline"]
KINDS: tuple[FaultKind, ...] = ("spike", "dropout", "flatline")


@dataclass(frozen=True)
class PlantedFault:
    machine: str
    day: date
    kind: FaultKind
    channel: str
    hours: tuple[int, ...]  # plant-local hour indexes 0..23 within the day


def draw_faults(
    machines: Sequence[str],
    days: Sequence[date],
    channels: Sequence[str],
    count: int,
    seed: int,
    kinds: Sequence[FaultKind] = KINDS,
) -> list[PlantedFault]:
    """`count` distinct (machine, day) faults, reproducible from `seed`."""
    rng = random.Random(seed)  # noqa: S311 (reproducible sampling, not security)
    slots = sorted((m, d) for m in machines for d in days)
    if count > len(slots):
        raise ValueError("more faults than (machine, day) slots")
    chosen = rng.sample(slots, count)
    out: list[PlantedFault] = []
    for machine, day in sorted(chosen):
        kind = rng.choice(list(kinds))
        channel = rng.choice(sorted(channels))
        span = 1 if kind == "spike" else rng.randint(6, 10)
        start = rng.randint(0, 24 - span)
        out.append(PlantedFault(machine, day, kind, channel, tuple(range(start, start + span))))
    return out


def plant(
    readings: dict[int, float], fault: PlantedFault, *, centre: float, scale: float, spreads: float
) -> dict[int, float]:
    """The day's hourly `readings` (hour -> value) of the faulted channel with the fault applied.
    A spike lands `spreads` robust scales above the centre; a dropout removes hours; a flatline
    holds the first hour's value."""
    out = dict(readings)
    if fault.kind == "spike":
        for hour in fault.hours:
            out[hour] = centre + spreads * scale
    elif fault.kind == "dropout":
        for hour in fault.hours:
            out.pop(hour, None)
    else:
        held = out[fault.hours[0]]
        for hour in fault.hours:
            out[hour] = held
    return out
