"""Baseline 2: naive fusion. Last-write-wins for the claim, and the day's readings AVERAGED.

The note was written after the readings, so last-write-wins takes the note's statement. The
sensor side is collapsed to the day's mean per channel and compared with the machine's own
history (mean +/- 3 standard deviations of ALL readings). A single bad hour barely moves a daily
mean, so the fused answer usually reads "normal"; the conflict is surfaced only if the mean itself
leaves the band. The averaged number has no single reading behind it, so its provenance is correct
only if exactly one reading produced it."""

from __future__ import annotations

import statistics

from trace_eval.baselines import BaselineAnswer, BaselineInput


def answer(case: BaselineInput) -> BaselineAnswer:
    means: dict[str, float] = {}
    outside: list[str] = []
    for channel, values in sorted(case.readings.items()):
        mean = statistics.fmean(values)
        history = case.history.get(channel, [])
        centre = statistics.fmean(history) if history else mean
        spread = statistics.pstdev(history) if len(history) > 1 else 0.0
        means[channel] = mean
        if spread > 0 and abs(mean - centre) > 3 * spread:
            outside.append(channel)
    claim = (
        "ran normally" if any("normally" in s.lower() for s in case.note_sentences) else "unknown"
    )
    figures = ", ".join(f"{c} mean {m:.2f}" for c, m in means.items())
    verdict = f"conflict on {', '.join(outside)}" if outside else "no conflict"
    return BaselineAnswer(
        name="fusion",
        answer_text=f"{case.machine} {claim} (last write wins); {figures}; {verdict}",
        score=max(means.values()) if means else None,
        surfaced_conflict=bool(outside),
        provenance_correct=all(len(v) == 1 for v in case.readings.values()),
    )
