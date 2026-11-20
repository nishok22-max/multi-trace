"""Evaluation report models (PRD 12.2). Every number is computed, never typed."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from trace_core.models.base import CoreModel, Sha256


class Prf(CoreModel):
    precision: float
    recall: float
    f1: float
    n: int = Field(ge=0)


class Wilson(CoreModel):
    """Proportion with a Wilson 95% interval."""

    point: float
    lower: float
    upper: float
    n: int = Field(ge=0)


class CalibrationBin(CoreModel):
    lo: float
    hi: float
    n: int = Field(ge=0)
    accuracy: float | None = None
    mean_confidence: float | None = None


class BaselineOutput(CoreModel):
    """The baseline's actual output, recorded and shown. Never typed in."""

    name: Literal["tfidf", "fusion", "nogate"]
    answer_text: str
    score: float | None = None
    surfaced_conflict: bool
    provenance_correct: bool


class EvalReport(CoreModel):
    run_id: str
    split: Literal["dev", "holdout"]
    config_hash: Sha256
    engine_sha: str
    lockfile_hash: Sha256
    overall: Prf
    per_fault: dict[str, Prf]
    false_conflict_rate: Wilson
    quiet_day_false_alarm: Wilson
    entity_accuracy_at1: float
    entity_accuracy_at3: float
    extraction_accuracy: dict[str, float]
    provenance_reresolve_rate: float
    gaps_read_as_normal: int = Field(ge=0)
    averaged_outputs: int = Field(ge=0)
    ece_before: float | None = None
    ece_after: float | None = None
    brier_before: float | None = None
    brier_after: float | None = None
    bins: list[CalibrationBin]
    baselines: list[BaselineOutput]
