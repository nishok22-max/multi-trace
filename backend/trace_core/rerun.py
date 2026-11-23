"""rerun_after_decision (B-10): a decision is applied to the parent version and everything
downstream is recomputed (holds -> gate -> conflicts -> confidence -> snapshot v+1).

The function is pure and works from the parent's own records (claims, review items, envelopes,
sources), so it needs no reader ports. Rules decide: an `entity` decision relinks the mention's
claims to the chosen entity (the old claim is kept as `supersedes`; ids change because the subject
is part of a claim's identity); `reading` accept/reject is applied by the holds stage; `escalate`
and `explain` change nothing here. Values are never averaged or edited.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.ids import build_claim, config_hash
from trace_core.models.case import Case, CaseVersion, VersionRecords
from trace_core.models.claims import ClaimRecord, Subject
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision, EntityChoice
from trace_core.normalise.time import fmt_utc
from trace_core.pipeline import compare_and_score, order_claims
from trace_core.ports import Clock
from trace_core.review.holds import latest_decisions
from trace_core.score.confidence import score_pre
from trace_core.snapshot.manifest import SnapshotInput, snapshot
from trace_core.stage_types import SnapshotHashes


def _relink(claim: ClaimRecord, entity_id: str) -> ClaimRecord:
    if claim.subject.link_status == "resolved" and claim.subject.entity_id == entity_id:
        return claim
    fields = claim.model_dump(mode="python")
    fields["subject"] = Subject(
        mention=claim.subject.mention,
        entity_id=entity_id,
        link_status="resolved",
        candidates=claim.subject.candidates,
        mention_key=claim.subject.mention_key,
    )
    fields["supersedes"] = claim.claim_id
    return build_claim(**fields)


def rerun_after_decision(
    parent: CaseVersion,
    decisions: Sequence[Decision],
    config: ConfigBundle,
    clock: Clock,
) -> CaseVersion:
    state = parent.views.state
    known = {d.decision_id: d for d in parent.records.decisions}
    known.update({d.decision_id: d for d in decisions})
    all_decisions = [known[k] for k in sorted(known)]
    latest = latest_decisions(all_decisions)

    claims = {c.claim_id: c for c in parent.records.claims}
    # Review items are append-only evidence: they keep the claim ids they were opened with, and
    # a relinked claim points back to its predecessor through `supersedes`.
    items = list(parent.records.review_items)
    for item in items:
        decision = latest.get(item.review_id)
        if decision is None or not isinstance(decision.choice, EntityChoice):
            continue
        successor = {c.supersedes: c.claim_id for c in claims.values() if c.supersedes}
        for original in item.claim_ids:
            cid = original
            while cid not in claims and cid in successor:
                cid = successor[cid]  # follow earlier relinks to the claim in force
            claim = claims.get(cid)
            if claim is None:
                continue
            new = _relink(claim, decision.choice.entity_id)
            del claims[cid]
            claims[new.claim_id] = new

    cfg_hash = config_hash(config)
    scored, comparisons, conflicts = compare_and_score(
        score_pre(order_claims(list(claims.values())), config),
        items,
        [],
        all_decisions,
        parent.records.envelopes,
        state.sources,
        config,
        cfg_hash,
    )
    records = VersionRecords(
        claims=scored,
        comparisons=comparisons,
        conflicts=conflicts,
        envelopes=parent.records.envelopes,
        review_items=sorted(items, key=lambda r: r.review_id),
        decisions=all_decisions,
    )
    case = Case(
        case_id=state.case_id,
        title=state.case_id,
        entities=state.scope_entities,
        window_start=state.window_start,
        window_end=state.window_end,
        plant_tz=state.plant_tz,
        created_at=fmt_utc(clock.now_utc()),
    )
    hashes = SnapshotHashes(
        config_hash=cfg_hash,
        engine_sha=parent.engine_sha,
        lockfile_hash=parent.lockfile_hash,
        canon_version=parent.canon_version,
        tesseract_version=parent.tesseract_version,
        traineddata_sha=parent.traineddata_sha,
        pdfium_version=parent.pdfium_version,
        tzdata_version=parent.tzdata_version,
    )
    return snapshot(
        case, parent, SnapshotInput(records=records, sources=list(state.sources)), hashes, clock
    )
