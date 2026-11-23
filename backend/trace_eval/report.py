"""Evaluation report files (D-08/D-09). The API's `EvalReport` model is frozen, so the bootstrap
intervals, the external-fault share and the disclosure live in a sidecar next to it
(`<name>.extras.json`). `required_problems` is the single list of what a complete report holds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_core.models.eval import EvalReport

REQUIRED_EXTRAS = ("ece_ci", "brier_ci", "external_fault_share", "disclosure", "seed", "cases")


def extras_path(path: Path) -> Path:
    return path.with_name(path.name + ".extras.json")


def save(report: EvalReport, extras: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    extras_path(path).write_text(
        json.dumps(extras, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def load(path: Path) -> tuple[EvalReport, dict[str, Any]]:
    report = EvalReport.model_validate_json(path.read_bytes())
    side = extras_path(path)
    extras: dict[str, Any] = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
    return report, extras


def required_problems(report: EvalReport, extras: dict[str, Any]) -> list[str]:
    """Why a report is incomplete (empty when it has everything PRD 12.2 asks for)."""
    problems: list[str] = []
    if not report.per_fault:
        problems.append("no per-fault precision/recall/F1")
    if report.overall.n == 0:
        problems.append("no planted conflicts in the overall score")
    if not report.bins or sum(b.n for b in report.bins) == 0:
        problems.append("no calibration bins with counts")
    if report.ece_before is None or report.brier_before is None:
        problems.append("ECE and Brier are missing")
    if not report.baselines or {b.name for b in report.baselines} != {"tfidf", "fusion", "nogate"}:
        problems.append("baseline outputs are missing")
    for key in REQUIRED_EXTRAS:
        if key not in extras:
            problems.append(f"extras.{key} is missing")
    return problems


def superseded(report: EvalReport, engine_sha_now: str) -> bool:
    """A report made by another engine than the one at HEAD must say so (T-31)."""
    return report.engine_sha != engine_sha_now
