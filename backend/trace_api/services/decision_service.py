"""Decisions use compute-then-commit (CLAUDE.md, D-05).

1. Read the latest version and validate the request against the item (choice kind, evidence hash).
2. Compute version v+1 with `rerun_after_decision` OUTSIDE any lock.
3. Append the new records, then ONE short `BEGIN IMMEDIATE` (`commit_decision`) re-checks that the
   latest version has not moved, the evidence hash and the already-decided rule, and inserts.
If the latest moved meanwhile, recompute and retry (bounded). A 409 is raised only for
`already-decided`, `evidence-changed` and `build-in-progress`.
Identity comes from the session; times from the clock.
"""

from __future__ import annotations

from collections.abc import Sequence

from trace_adapters.config_loader import load_config_bundle
from trace_adapters.sqlite.builds import BuildRepository
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.deps import AuthContext
from trace_api.problems import PROBLEM_BASE, ProblemError, not_found
from trace_core.errors import AlreadyDecided, EvidenceChanged
from trace_core.ids import decision_id, review_event_id
from trace_core.models.api_io import DecisionRequest, DecisionResponse, choice_allowed
from trace_core.models.records import Decision, ReviewEvent
from trace_core.normalise.time import fmt_utc
from trace_core.ports import Clock, Committed
from trace_core.rerun import rerun_after_decision
from trace_core.review.rules import event_kind_for

MAX_ATTEMPTS = 3
NO_STORE = {"Cache-Control": "no-store"}


def _conflict(type_: str, title: str, retry_after: int | None = None) -> ProblemError:
    headers = dict(NO_STORE)
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return ProblemError(
        409, title, type_=PROBLEM_BASE + type_, headers=headers, retry_after=retry_after
    )


def decide(
    store: SqliteClaimStore,
    builds: BuildRepository,
    clock: Clock,
    auth: AuthContext,
    case_id: str,
    review_id: str,
    body: DecisionRequest,
) -> DecisionResponse:
    if builds.in_flight(case_id):
        raise _conflict("build-in-progress", "Build in progress", retry_after=5)
    config = load_config_bundle()
    for _ in range(MAX_ATTEMPTS):
        latest = store.latest(case_id)
        if latest is None:
            raise not_found()
        item = next((i for i in latest.records.review_items if i.review_id == review_id), None)
        if item is None:
            raise not_found()
        if not choice_allowed(item.type, body.choice) or body.base_version > latest.version:
            raise ProblemError(422, "Unprocessable Entity", headers=NO_STORE)
        if item.evidence_hash != body.shown_evidence_hash:
            raise _conflict("evidence-changed", "Evidence changed")
        now = fmt_utc(clock.now_utc())
        decision = Decision(
            decision_id=decision_id(review_id, auth.principal, body.base_version, body.choice),
            case_id=case_id,
            review_id=review_id,
            principal=auth.principal,
            display_name_snapshot=auth.display_name,
            role_snapshot=auth.role,
            choice=body.choice,
            reason=body.reason,
            base_version=body.base_version,
            shown_evidence_hash=body.shown_evidence_hash,
            supersedes=body.supersedes,
            at=now,
        )
        child = rerun_after_decision(latest, [decision], config, clock)  # no lock held
        seq = max((e.seq for e in store.review_events(case_id, review_id)), default=-1) + 1
        kind = event_kind_for(body.choice)
        event = ReviewEvent(
            event_id=review_event_id(review_id, kind, seq),
            seq=seq,
            review_id=review_id,
            kind=kind,
            decision_id=decision.decision_id,
            at=now,
        )
        records: Sequence[object] = [
            *child.records.claims,
            *child.records.comparisons,
            *child.records.conflicts,
        ]
        store.append(case_id, records)  # type: ignore[arg-type]  # idempotent, append-only
        try:
            result = store.commit_decision(case_id, latest.version, decision, event, child)
        except AlreadyDecided:
            raise _conflict("already-decided", "Already decided") from None
        except EvidenceChanged:
            raise _conflict("evidence-changed", "Evidence changed") from None
        if isinstance(result, Committed):
            return DecisionResponse(
                decision_id=decision.decision_id,
                version=result.version,
                manifest_hash=result.manifest_hash,
            )
    raise _conflict("build-in-progress", "Build in progress", retry_after=1)
