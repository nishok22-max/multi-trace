"""Baseline 3: no gate. Any two claims that differ are a conflict: no entity, time or unit check.

Used to count the false conflicts the comparability gate prevents. A "pair" here is two statements
about the world as a naive system sees them: (entity, day, unit, value). The baseline flags a
conflict whenever the values differ; the gate flags one only when the pair is comparable."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Statement:
    entity: str
    day: str
    unit: str | None
    value: str


def flags_conflict(a: Statement, b: Statement) -> bool:
    """No gate: different values are a conflict, whatever the entity, day or unit."""
    return a.value != b.value


def comparable(a: Statement, b: Statement) -> bool:
    """What the gate requires before any value is judged (checks 1, 3 and 4 in miniature)."""
    return a.entity == b.entity and a.day == b.day and a.unit == b.unit


def false_conflicts(pairs: list[tuple[Statement, Statement]]) -> tuple[int, int]:
    """(conflicts flagged on NON-comparable pairs, non-comparable pairs). The gate's own count on
    the same pairs is measured by running the real gate; see the runner."""
    non_comparable = [(a, b) for a, b in pairs if not comparable(a, b)]
    return sum(1 for a, b in non_comparable if flags_conflict(a, b)), len(non_comparable)
