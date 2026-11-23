"""Confidence scoring (B-09, PRD 10.8). Always uncalibrated until a calibration fit exists.

raw = extractor x entity_link x time_precision x unit_factor x reliability_adj
      x (1 + lambda x independent_corroboration), clipped to [0, 1].

Every factor is derived from the claim itself, never typed:
- extractor: the reader's prior, already stored in `components["extractor"]`;
- entity_link: the winning candidate's score for a resolved subject, 0 when not resolved;
- time_precision: 1 for a known valid time, 0 for unknown (no date, no confidence);
- unit_factor: 0 for a numeric value whose unit is unknown, otherwise 1;
- reliability_adj: 0.5 + r with the neutral prior r = 0.5 (source reliability is applied once the
  scorer is given sources; it is neutral until then, so 1.0);
- corroboration: 0 in `score_pre`; in `score`, the number of claims that agree with it through a
  comparison AND come from sources with declared, disjoint provenance. Undeclared provenance
  gives zero credit (PRD 10.7). `score` never alters holds.

Sensor-state claims keep the conformal confidence computed by `derive_sensor_state`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from trace_core.ids import claim_record_hash
from trace_core.models.claims import ClaimRecord, Confidence
from trace_core.models.config import ConfigBundle
from trace_core.models.evidence import EvidencePointer
from trace_core.models.records import ComparisonRecord
from trace_core.models.time import Interval
from trace_core.read.hidden_text import FALLBACK_NOTE
from trace_core.stage_types import Provenance

NEUTRAL_RELIABILITY_ADJ = 1.0
_BASE_FACTORS = ("extractor", "entity_link", "time_precision", "unit_factor", "reliability_adj")


def _entity_link(claim: ClaimRecord) -> float:
    subject = claim.subject
    if subject.link_status != "resolved" or subject.entity_id is None:
        return 0.0
    for cand in subject.candidates:
        if cand.entity_id == subject.entity_id:
            return cand.score
    return 1.0  # resolved by a structured id (e.g. a machineID column)


def _time_precision(claim: ClaimRecord) -> float:
    return 1.0 if isinstance(claim.temporal.valid_time, Interval) else 0.0


def _unit_factor(claim: ClaimRecord) -> float:
    numeric = claim.value_type == "numeric"
    return 0.0 if numeric and claim.unit_status == "unknown" else 1.0


def _scorable(claim: ClaimRecord) -> bool:
    return "extractor" in claim.confidence.components and claim.modality != "sensor"


def _with_confidence(claim: ClaimRecord, confidence: Confidence) -> ClaimRecord:
    # confidence is not part of the claim id; only the record hash changes
    updated = claim.model_copy(update={"confidence": confidence})
    return updated.model_copy(update={"record_hash": claim_record_hash(updated)})


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def score_pre(claims: Sequence[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    """Pre-confidence; corroboration = 0."""
    out: list[ClaimRecord] = []
    for claim in claims:
        if not _scorable(claim):
            out.append(claim)
            continue
        components = {
            "extractor": claim.confidence.components["extractor"],
            "entity_link": _entity_link(claim),
            "time_precision": _time_precision(claim),
            "unit_factor": _unit_factor(claim),
            "reliability_adj": NEUTRAL_RELIABILITY_ADJ,
            "corroboration": 0.0,
        } | (
            {"visibility_fallback": 1.0}
            if "visibility_fallback" in claim.confidence.components
            else {}
        )
        value = 1.0
        for name in _BASE_FACTORS:
            value *= components[name]
        out.append(
            _with_confidence(
                claim,
                Confidence(
                    value=_clip(value),
                    calibrated=False,
                    components=components,
                    stage="pre",
                    note="uncalibrated: product of extractor, link, time, unit and reliability"
                    + ("; " + FALLBACK_NOTE if "visibility_fallback" in components else ""),
                ),
            )
        )
    return out


def _ancestry(source: str, derived: Mapping[str, list[str]]) -> frozenset[str] | None:
    """The source plus everything it was derived from; None if provenance is undeclared."""
    if source not in derived:
        return None
    seen: set[str] = set()
    todo = [source]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        todo.extend(derived.get(current, []))
    return frozenset(seen)


def _source_of(claim: ClaimRecord) -> str | None:
    ev: EvidencePointer | None = claim.evidence
    return getattr(ev, "source_id", None)


def score(
    claims: Sequence[ClaimRecord],
    comparisons: Sequence[ComparisonRecord],
    provenance: Provenance,
    cfg: ConfigBundle,
) -> list[ClaimRecord]:
    """Final confidence. Never alters holds."""
    by_id = {c.claim_id: c for c in claims}
    partners: dict[str, set[str]] = {}
    for cmp in comparisons:
        if cmp.outcome == "agree":
            partners.setdefault(cmp.claim_a, set()).add(cmp.claim_b)
            partners.setdefault(cmp.claim_b, set()).add(cmp.claim_a)
    out: list[ClaimRecord] = []
    for claim in claims:
        if not _scorable(claim) or claim.confidence.stage != "pre":
            out.append(claim)
            continue
        own_source = _source_of(claim)
        own = _ancestry(own_source, provenance.derived_from) if own_source else None
        groups: list[frozenset[str]] = []
        for pid in sorted(partners.get(claim.claim_id, set())):
            other = by_id.get(pid)
            other_source = _source_of(other) if other is not None else None
            theirs = _ancestry(other_source, provenance.derived_from) if other_source else None
            if own is None or theirs is None or own & theirs:
                continue  # undeclared or overlapping provenance: no credit
            if theirs not in groups:
                groups.append(theirs)  # one credit per distinct independent provenance
        n = len(groups)
        comps = dict(claim.confidence.components)
        comps["corroboration"] = float(n)
        base = 1.0
        for name in _BASE_FACTORS:
            base *= comps.get(name, 1.0)
        value = _clip(base * (1.0 + cfg.gate.lambda_corroboration * n))
        out.append(
            _with_confidence(
                claim,
                Confidence(
                    value=value,
                    calibrated=False,
                    components=comps,
                    stage="final",
                    note="uncalibrated: pre-score x (1 + lambda x independent corroboration)",
                ),
            )
        )
    return out
