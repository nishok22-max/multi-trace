"""Label kit (D-12, PRD 12.1): export claims and comparisons for a person who did not build the
engine to label, and import the labels. The labeller id is recorded with every row, and the
hand-labelled set's source (builder vs outsider) is disclosed in the report."""

from __future__ import annotations

from dataclasses import dataclass

import yaml

FIELDS = ("entity", "value", "unit", "time", "outcome")
OUTCOMES = ("agree", "disagree", "cant_compare", "cant_tell")


@dataclass(frozen=True)
class LabelRow:
    claim_id: str
    statement: str
    entity: str | None = None
    value: str | None = None
    unit: str | None = None
    time: str | None = None
    outcome: str | None = None


def export_yaml(rows: list[LabelRow], labeller: str = "") -> str:
    """Rows to fill in. Fields are `null` until labelled."""
    doc = {
        "labeller": labeller,
        "rows": [
            {
                "claim_id": r.claim_id,
                "statement": r.statement,
                **{f: getattr(r, f) for f in FIELDS},
            }
            for r in rows
        ],
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def import_yaml(text: str) -> tuple[str, list[LabelRow]]:
    """(labeller id, rows). Refuses a file without a labeller, or with an unknown outcome."""
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or not str(doc.get("labeller", "")).strip():
        raise ValueError("the labeller id is required")
    rows: list[LabelRow] = []
    for raw in doc.get("rows", []):
        outcome = raw.get("outcome")
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        rows.append(
            LabelRow(
                claim_id=str(raw["claim_id"]),
                statement=str(raw["statement"]),
                **{f: (None if raw.get(f) is None else str(raw[f])) for f in FIELDS},
            )
        )
    return str(doc["labeller"]), rows
