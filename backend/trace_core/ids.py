"""Content-addressed IDs (IMPLEMENTATION_PLAN C.1a). `h` = sha256(JCS(...))[:24].

IDs never depend on wall-clock time, labels, statements or confidence, so a rebuild with a
different clock or a score re-run yields the same IDs (promise 8, determinism).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from trace_core.canonical import canonical_sha256, record_hash
from trace_core.errors import CanonicalizationError
from trace_core.models.claims import ClaimRecord, MentionKey
from trace_core.models.config import ConfigBundle, EnvelopeConfig
from trace_core.models.evidence import CacheKey, Principal
from trace_core.models.records import Choice

_PLACEHOLDER_ID = "clm_" + "0" * 24
_PLACEHOLDER_SHA = "0" * 64


def _h(obj: Any) -> str:
    return canonical_sha256(obj)[:24]


def config_hash(bundle: ConfigBundle) -> str:
    """sha256(JCS(bundle)): full 64 hex."""
    return canonical_sha256(bundle)


def cache_key_digest(key: CacheKey) -> str:
    return canonical_sha256(key)


def claim_semantic(claim: ClaimRecord) -> dict[str, Any]:
    """Fields that define what a claim *is*. Excludes label, statement, confidence,
    link candidates, supersedes and wall-clock fields."""
    subject = claim.subject
    return {
        "case_id": claim.case_id,
        "claim_type": claim.claim_type,
        "subject": {
            "mention": subject.mention,
            "entity_id": subject.entity_id,
            "mention_key": subject.mention_key,
        },
        "attribute": claim.attribute,
        "value": claim.value,
        "value_type": claim.value_type,
        "unit": claim.unit,
        "unit_status": claim.unit_status,
        "normalized_value": claim.normalized_value,
        "normalized_unit": claim.normalized_unit,
        "temporal": claim.temporal,
        "modality": claim.modality,
        "evidence": claim.evidence,
        "derived_from": sorted(claim.derived_from),
        "method": claim.method,
    }


def claim_id(claim: ClaimRecord) -> str:
    return "clm_" + _h(claim_semantic(claim))


def claim_record_hash(claim: ClaimRecord) -> str:
    """sha256(JCS(body minus wall-clock fields)); the hash field itself is excluded."""
    return record_hash(claim, exclude=frozenset({"record_hash"}))


def build_claim(**fields: Any) -> ClaimRecord:
    """Validate the fields, then fill `claim_id` and `record_hash` from content."""
    fields = {**fields, "claim_id": _PLACEHOLDER_ID, "record_hash": _PLACEHOLDER_SHA}
    draft = ClaimRecord.model_validate(fields)
    with_id = draft.model_copy(update={"claim_id": claim_id(draft)})
    return with_id.model_copy(update={"record_hash": claim_record_hash(with_id)})


def verify_claim(claim: ClaimRecord) -> bool:
    """True when the stored id and hash match the content."""
    return claim.claim_id == claim_id(claim) and claim.record_hash == claim_record_hash(claim)


def comparison_id(claim_ids: Sequence[str], cfg_hash: str) -> str:
    return "cmp_" + _h({"claims": sorted(claim_ids), "config_hash": cfg_hash})


def conflict_id(side_claim_ids: Sequence[str]) -> str:
    return "cf_" + _h({"sides": sorted(side_claim_ids)})


def review_id(review_type: str, mention_keys: Sequence[MentionKey]) -> str:
    """Stable across extractor versions: depends on (type, sorted mention keys) only."""
    if not mention_keys:
        raise CanonicalizationError("a review item needs at least one mention key")
    keys = sorted([mk.source_sha256, mk.locator] for mk in mention_keys)
    return "rv_" + _h({"type": review_type, "mention_keys": keys})


def review_event_id(rid: str, kind: str, seq: int) -> str:
    return "rve_" + _h({"review_id": rid, "kind": kind, "seq": seq})


def decision_id(rid: str, principal: Principal, base_version: int, choice: Choice) -> str:
    return "dec_" + _h(
        {"review_id": rid, "principal": principal, "base_version": base_version, "choice": choice}
    )


def envelope_id(
    machine: str,
    series_id: str,
    scope: Sequence[str],
    statistic: str,
    granularity: str,
    quiet_days: Sequence[str],
    params: EnvelopeConfig,
    pool_members: Sequence[str],
    partition_hashes: dict[str, str],
) -> str:
    return "env_" + _h(
        {
            "machine": machine,
            "series_id": series_id,
            "scope": sorted(scope),
            "statistic": statistic,
            "granularity": granularity,
            "quiet_days": sorted(quiet_days),
            "params": params,
            "pool_members": sorted(pool_members),
            "partition_hashes": partition_hashes,
        }
    )
