"""Baseline 1: similarity search (offline TF-IDF), answering from the best-matching chunk.

The index holds the note's sentences and one text chunk per sensor channel (a summary line of the
day's readings). The question is retrieved against it and the top chunk is the answer. The answer
cites a single chunk; it is "provenance correct" only if it cites every source the claim needs
(the note AND the sensor evidence), and it "surfaces a conflict" only if the answer text itself
contradicts the note. Both flags are computed from what was retrieved."""

from __future__ import annotations

import math
import re
from collections import Counter

from trace_eval.baselines import BaselineAnswer, BaselineInput

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    return {t: c * idf.get(t, 0.0) for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def answer(case: BaselineInput) -> BaselineAnswer:
    chunks: list[tuple[str, str]] = [("note", s) for s in case.note_sentences]
    for channel, values in sorted(case.readings.items()):
        low, high = min(values), max(values)
        chunks.append(
            ("sensor", f"{channel} readings on {case.day}: lowest {low:.2f} highest {high:.2f}")
        )
    docs = [_tokens(text) for _, text in chunks]
    n = len(docs)
    df = Counter(t for d in docs for t in set(d))
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    question = f"did {case.machine} run normally on {case.day}"
    q = _vector(_tokens(question), idf)
    scored = sorted(
        ((_cosine(q, _vector(d, idf)), i) for i, d in enumerate(docs)), key=lambda x: (-x[0], x[1])
    )
    score, best = scored[0]
    source, text = chunks[best]
    surfaced = source == "sensor" and any("normally" in s.lower() for s in case.note_sentences)
    # "provenance correct": the answer rests on both the note and the sensor evidence
    cited = {source}
    return BaselineAnswer(
        name="tfidf",
        answer_text=f"[{source}] {text}",
        score=score,
        surfaced_conflict=surfaced,
        provenance_correct=cited == {"note", "sensor"},
    )
