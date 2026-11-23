"""Baselines (D-07, PRD 12.3): what a similarity search and a naive fusion say about the SAME
seeded faults, recorded as output (answer text and score), never typed in. They may average: this
package is outside the never-average gate on purpose, because averaging is the thing it shows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineInput:
    """One case as a baseline sees it: free text and raw readings, no entities or units."""

    machine: str
    day: str  # plant-local YYYY-MM-DD
    note_sentences: list[str]  # the written report, one sentence per item
    note_written_at: str  # UTC time the note was written
    readings: dict[str, list[float]]  # channel -> the day's readings
    history: dict[str, list[float]]  # channel -> all readings of the machine's other days


@dataclass(frozen=True)
class BaselineAnswer:
    name: str
    answer_text: str
    score: float | None
    surfaced_conflict: bool
    provenance_correct: bool
