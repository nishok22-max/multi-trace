"""Review holds (B-09/B-10). A held claim never pairs (test_held_claims_never_pair).

A claim is held when
- its subject is not resolved (the entity is a decision for a human);
- a review item names it and that item is not closed by a valid decision;
- its pre-confidence is below `tau_review` (reader claims only; sensor-state confidence is a
  conformal p-value and is never a hold criterion).
`reading=reject` keeps a claim held for good. An `entity` or `reading=accept` decision releases it
(an entity decision is applied by the re-run before holds are evaluated). `escalate` and `explain`
never close an item. A decision is invalidated by a later `stale` event on its item.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle
from trace_core.models.records import Decision, ReadingChoice, ReviewEvent, ReviewItem
from trace_core.review.rules import closes_item


def latest_decisions(decisions: Sequence[Decision]) -> dict[str, Decision]:
    """Per review item the decision that is not superseded (ties: latest `at`, then id)."""
    superseded = {d.supersedes for d in decisions if d.supersedes is not None}
    live = [d for d in decisions if d.decision_id not in superseded and closes_item(d.choice)]
    out: dict[str, Decision] = {}
    for d in sorted(live, key=lambda d: (d.at, d.decision_id)):
        out[d.review_id] = d
    return out


def _stale(review_id: str, events: Sequence[ReviewEvent]) -> bool:
    mine = sorted((e for e in events if e.review_id == review_id), key=lambda e: e.seq)
    state = [e.kind for e in mine if e.kind in ("opened", "decided", "stale")]
    return bool(state) and state[-1] == "stale"


def apply_holds(
    claims: Sequence[ClaimRecord],
    review_items: Sequence[ReviewItem],
    events: Sequence[ReviewEvent],
    decisions: Sequence[Decision],
    cfg: ConfigBundle,
) -> tuple[list[ClaimRecord], list[ClaimRecord]]:
    """Returns (eligible, held). Uses pre-confidence."""
    decided = latest_decisions(decisions)
    released: set[str] = set()
    rejected: set[str] = set()
    open_claims: set[str] = set()
    for item in review_items:
        decision = decided.get(item.review_id)
        if decision is None or _stale(item.review_id, events):
            open_claims.update(item.claim_ids)
        elif isinstance(decision.choice, ReadingChoice) and decision.choice.verdict == "reject":
            rejected.update(item.claim_ids)
        else:
            released.update(item.claim_ids)
    eligible: list[ClaimRecord] = []
    held: list[ClaimRecord] = []
    for claim in claims:
        cid = claim.claim_id
        low = (
            "extractor" in claim.confidence.components
            and claim.confidence.value < cfg.gate.tau_review
        )
        unresolved = claim.subject.link_status != "resolved"
        is_held = (
            cid in rejected or cid in open_claims or ((low or unresolved) and cid not in released)
        )
        (held if is_held else eligible).append(claim)
    return eligible, held
