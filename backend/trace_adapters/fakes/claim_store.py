"""MemClaimStore: in-memory ClaimStore with the same semantics as SqliteClaimStore."""

from __future__ import annotations

from collections.abc import Sequence

from trace_core.canonical import record_hash
from trace_core.errors import AlreadyDecided, AppendOnlyViolation, EvidenceChanged, IntegrityError
from trace_core.models.case import Case, CaseVersion, VersionMembers
from trace_core.models.claims import ClaimRecord
from trace_core.models.records import (
    ComparisonRecord,
    ConflictRecord,
    Decision,
    Envelope,
    ReviewEvent,
    ReviewItem,
    Source,
)
from trace_core.ports import AppendableRecord, Committed, Moved
from trace_core.review.rules import closes_item, event_kind_for


class MemClaimStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, ...], tuple[str, AppendableRecord]] = {}
        self._decisions: dict[tuple[str, str], Decision] = {}
        self._versions: dict[str, list[CaseVersion]] = {}
        self._members: dict[tuple[str, int], VersionMembers] = {}

    # ---------------------------------------------------------------------- append
    def append(self, case_id: str, records: Sequence[AppendableRecord]) -> None:
        staged = dict(self._rows)  # all-or-nothing, like a transaction
        for rec in records:
            self._put(staged, case_id, rec)
        self._rows = staged

    @staticmethod
    def _key(case_id: str, rec: AppendableRecord) -> tuple[str, ...]:
        if isinstance(rec, Case):
            return ("case", rec.case_id)
        if isinstance(rec, Source):
            return ("source", case_id, rec.source_id)
        if isinstance(rec, ClaimRecord):
            return ("claim", case_id, rec.claim_id)
        if isinstance(rec, ComparisonRecord):
            return ("comparison", case_id, rec.comparison_id)
        if isinstance(rec, ConflictRecord):
            return ("conflict", case_id, rec.conflict_id)
        if isinstance(rec, Envelope):
            return ("envelope", case_id, rec.envelope_id)
        if isinstance(rec, ReviewItem):
            return ("review_item", case_id, rec.review_id)
        return ("review_event", rec.review_id, str(rec.seq))

    def _put(
        self,
        rows: dict[tuple[str, ...], tuple[str, AppendableRecord]],
        case_id: str,
        rec: AppendableRecord,
    ) -> None:
        if isinstance(rec, Case | Source | ClaimRecord) and rec.case_id != case_id:
            raise ValueError("record belongs to a different case")
        key = self._key(case_id, rec)
        digest = rec.record_hash if isinstance(rec, ClaimRecord) else record_hash(rec)
        existing = rows.get(key)
        if existing is not None:
            if existing[0] != digest:
                raise AppendOnlyViolation("record exists with different content")
            return
        if isinstance(rec, ReviewEvent) and ("review_item", case_id, rec.review_id) not in rows:
            raise IntegrityError("review event for an unknown review item")
        rows[key] = (digest, rec)

    def _all(self, kind: str, case_id: str) -> list[AppendableRecord]:
        return [r for k, (_, r) in self._rows.items() if k[0] == kind and k[1] == case_id]

    # -------------------------------------------------------------------- versions
    def put_version(self, version: CaseVersion, members: VersionMembers) -> None:
        self._check_version(version, members)
        self._versions.setdefault(version.case_id, []).append(version)
        self._members[(version.case_id, version.version)] = members

    def _check_version(self, version: CaseVersion, members: VersionMembers) -> None:
        chain = self._versions.get(version.case_id, [])
        latest_v = chain[-1].version if chain else 0
        latest_hash = chain[-1].manifest_hash if chain else None
        if version.version != latest_v + 1:
            raise IntegrityError("version must be latest + 1")
        if version.parent_manifest_hash != latest_hash:
            raise IntegrityError("parent_manifest_hash does not chain to the latest version")
        wanted = (
            ("claim", members.claim_ids),
            ("comparison", members.comparison_ids),
            ("conflict", members.conflict_ids),
        )
        for kind, ids in wanted:
            for rid in ids:
                if (kind, version.case_id, rid) not in self._rows:
                    raise IntegrityError(f"version member {rid} was never appended")

    def get_version(self, case_id: str, version: int) -> CaseVersion | None:
        chain = self._versions.get(case_id, [])
        return chain[version - 1] if 1 <= version <= len(chain) else None

    def latest(self, case_id: str) -> CaseVersion | None:
        chain = self._versions.get(case_id, [])
        return chain[-1] if chain else None

    def load_claims(self, case_id: str, version: int) -> list[ClaimRecord]:
        members = self._members.get((case_id, version))
        if members is None:
            return []
        claims = [self._rows[("claim", case_id, cid)][1] for cid in members.claim_ids]
        typed = [c for c in claims if isinstance(c, ClaimRecord)]

        def order(c: ClaimRecord) -> tuple[str, str]:
            return (getattr(c.temporal.valid_time, "start", None) or "9999", c.claim_id)

        return sorted(typed, key=order)

    def review_events(self, case_id: str, review_id: str | None = None) -> list[ReviewEvent]:
        events = [
            rec
            for key, (_, rec) in self._rows.items()
            if key[0] == "review_event"
            and isinstance(rec, ReviewEvent)
            and ("review_item", case_id, rec.review_id) in self._rows
            and (review_id is None or rec.review_id == review_id)
        ]
        return sorted(events, key=lambda e: (e.review_id, e.seq))

    # ------------------------------------------------------------------- decisions
    def commit_decision(
        self,
        case_id: str,
        expected_latest: int,
        decision: Decision,
        event: ReviewEvent,
        version: CaseVersion,
    ) -> Committed | Moved:
        if decision.case_id != case_id or version.case_id != case_id:
            raise ValueError("decision and version must belong to the case")
        if event.review_id != decision.review_id or event.decision_id != decision.decision_id:
            raise ValueError("event does not match the decision")
        if event.kind != event_kind_for(decision.choice):
            raise ValueError("event kind does not match the decision choice")
        chain = self._versions.get(case_id, [])
        latest = chain[-1].version if chain else 0
        if latest != expected_latest:
            return Moved(latest=latest)
        item = self._rows.get(("review_item", case_id, decision.review_id))
        if item is None or not isinstance(item[1], ReviewItem):
            raise ValueError("unknown review item")
        if item[1].evidence_hash != decision.shown_evidence_hash:
            raise EvidenceChanged("evidence changed since it was shown")
        existing_events = self.review_events(case_id, decision.review_id)
        if closes_item(decision.choice) and decision.supersedes is None:
            for e in existing_events:
                prior = self._decisions.get((case_id, e.decision_id or ""))
                if e.kind == event.kind and prior is not None and prior.choice.type != "escalate":
                    raise AlreadyDecided(prior.decision_id)
        nxt = max((e.seq for e in existing_events), default=-1) + 1
        if event.seq != nxt:
            raise ValueError("event seq must be the next sequence number for the item")
        members = VersionMembers.from_records(version.records)
        self._check_version(version, members)
        # all checks passed: apply
        self._decisions[(case_id, decision.decision_id)] = decision
        self._put(self._rows, case_id, event)
        self._versions.setdefault(case_id, []).append(version)
        self._members[(case_id, version.version)] = members
        return Committed(version=version.version, manifest_hash=version.manifest_hash)
