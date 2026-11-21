"""Display labels (C-17, S-88, ...) come from `seed/labels.yaml`, never from the engine.

A label is a display alias keyed by a stable claim key. It never feeds an ID or an outcome
(claim ids exclude the label), so relabelling cannot change what the engine decides.
"""

from __future__ import annotations

from collections.abc import Mapping

import yaml

from trace_core.ids import claim_record_hash
from trace_core.models.claims import ClaimRecord
from trace_core.models.evidence import SensorWindowPointer, TextSpanPointer
from trace_core.models.time import Interval
from trace_core.normalise.time import local_date

LABELS_SOURCE_ID = "labels"


def parse_labels(data: bytes) -> dict[str, str]:
    loaded = yaml.safe_load(data.decode("utf-8")) or {}
    raw = loaded.get("labels", {})
    return {str(key): str(value) for key, value in raw.items()}


def label_key(claim: ClaimRecord, plant_tz: str) -> str | None:
    """Stable key of a claim for label lookup. None: this kind of claim is never labelled."""
    ev = claim.evidence
    if isinstance(ev, TextSpanPointer):
        return f"text|{ev.source_id}|p{ev.page}|l{ev.line}|{claim.attribute}"
    rule = claim.method.rule_id or ""
    entity = claim.subject.entity_id
    vt = claim.temporal.valid_time
    if isinstance(ev, SensorWindowPointer) and isinstance(vt, Interval) and entity is not None:
        day = local_date(vt.start, plant_tz).isoformat()
        if rule.startswith("state."):
            return f"sensor|{entity}|{claim.attribute}|day|{day}"
        if rule == "excursion.hourly_peak":
            return f"sensor|{entity}|hourly_peak|{day}"
    return None


def apply_labels(
    claims: list[ClaimRecord], labels: Mapping[str, str], plant_tz: str
) -> list[ClaimRecord]:
    out: list[ClaimRecord] = []
    for claim in claims:
        key = label_key(claim, plant_tz)
        label = labels.get(key) if key is not None else None
        if label is None or label == claim.label:
            out.append(claim)
            continue
        relabelled = claim.model_copy(update={"label": label})
        out.append(relabelled.model_copy(update={"record_hash": claim_record_hash(relabelled)}))
    return out
