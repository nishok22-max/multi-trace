"""Precomputed views (D-04/D-05 minimal): the five-step story and the timeline.

Every number in a story text is formatted from a record (promise 8); nothing is typed here.
"""

from __future__ import annotations

from trace_core.compare.quantifiers import sensor_state_of
from trace_core.models.case import Story, StoryStep, TimelineEntry, VersionRecords
from trace_core.models.claims import ClaimRecord
from trace_core.models.time import Interval


def _name(claim: ClaimRecord) -> str:
    return claim.label or claim.claim_id


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def build_story(records: VersionRecords) -> Story:
    by_id = {c.claim_id: c for c in records.claims}
    conflict = records.conflicts[0] if records.conflicts else None
    if conflict is None:
        return Story(
            steps=[
                StoryStep(
                    n=1,
                    title="What the records say",
                    text=f"{len(records.claims)} claims were read; no conflict was found.",
                ),
                *[
                    StoryStep(n=n, title=title, text="Nothing to compare yet.")
                    for n, title in (
                        (2, "What the sensor says"),
                        (3, "Can they be compared?"),
                        (4, "Outcome"),
                        (5, "What is kept"),
                    )
                ],
            ],
            headline_outcome=None,
        )
    sides = [by_id[s] for s in conflict.sides if s in by_id]
    text_side = next((c for c in sides if c.modality == "text"), None)
    sensor_side = next((c for c in sides if c.modality == "sensor"), None)
    comparison = next(
        (c for c in records.comparisons if c.comparison_id in conflict.comparison_ids), None
    )
    state = sensor_state_of(sensor_side) if sensor_side else None
    passed = sum(1 for c in comparison.checks if c.passed) if comparison else 0
    total = len(comparison.checks) if comparison else 0
    steps = [
        StoryStep(
            n=1,
            title="What the note says",
            text=(f"{_name(text_side)}: {text_side.statement}." if text_side else "No note side."),
            claim_ids=[text_side.claim_id] if text_side else [],
        ),
        StoryStep(
            n=2,
            title="What the sensor says",
            text=f"{_name(sensor_side)}: {sensor_side.statement}."
            if sensor_side
            else "No sensor side.",
            claim_ids=[sensor_side.claim_id] if sensor_side else [],
        ),
        StoryStep(
            n=3,
            title="Can they be compared?",
            text=(
                f"The gate ran {total} checks in order and {passed} passed: same machine, same "
                "attribute, same day, same scale, data on both sides, and a violation test."
            ),
            comparison_ids=[comparison.comparison_id] if comparison else [],
        ),
        StoryStep(
            n=4,
            title="Outcome",
            text=(comparison.reason if comparison else "No comparison."),
            comparison_ids=[comparison.comparison_id] if comparison else [],
        ),
        StoryStep(
            n=5,
            title="What is kept",
            text=(
                "Both sides are kept and nothing is averaged. "
                + (
                    f"The measured statistic is {_fmt(state.t_d)} against a threshold of "
                    f"{_fmt(state.t_star)}. "
                    if state
                    else ""
                )
                + "Confidences are uncalibrated."
            ),
            claim_ids=[c.claim_id for c in sides],
        ),
    ]
    return Story(steps=steps, headline_outcome=comparison.outcome if comparison else None)


def build_timeline(records: VersionRecords, plant_tz: str) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for claim in records.claims:
        vt = claim.temporal.valid_time
        interval = vt if isinstance(vt, Interval) else None
        entries.append(
            TimelineEntry(
                entry_id=claim.claim_id,
                claim_id=claim.claim_id,
                entity_id=claim.subject.entity_id,
                start=interval.start if interval else None,
                end=interval.end if interval else None,
                granularity=interval.granularity if interval else "unknown",
                attribute=claim.attribute,
                modality=claim.modality,
                label=claim.label or claim.statement[:80],
            )
        )
    return sorted(entries, key=lambda e: (e.start or "9999", e.claim_id))
