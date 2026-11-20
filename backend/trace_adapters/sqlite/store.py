"""SqliteClaimStore: implements ClaimStore on one SQLite file (WAL).

Rules (IMPLEMENTATION_PLAN A.2, SYSTEM_DESIGN 8):
- `isolation_level=None` everywhere, with an explicit `BEGIN IMMEDIATE` for every write;
- PRAGMAs: journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON,
  mmap_size=64 MiB (plus recursive_triggers=ON so INSERT OR REPLACE cannot dodge the
  append-only delete trigger);
- the repository exposes NO update or delete method for evidence. Inserts are
  `INSERT OR IGNORE` followed by a hash comparison, never `OR REPLACE`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from trace_adapters.sqlite.migrate import apply_migrations
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

_MMAP = 64 * 1024 * 1024


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA mmap_size={_MMAP}")
    conn.execute("PRAGMA recursive_triggers=ON")
    return conn


def _json(
    model: Case
    | Source
    | ClaimRecord
    | ComparisonRecord
    | ConflictRecord
    | Envelope
    | ReviewItem
    | ReviewEvent
    | Decision
    | CaseVersion,
) -> str:
    return model.model_dump_json(by_alias=True)


class SqliteClaimStore:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        conn = connect(self._path)
        try:
            apply_migrations(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------ connections
    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self._path)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self._path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    # ---------------------------------------------------------------------- append
    def append(self, case_id: str, records: Sequence[AppendableRecord]) -> None:
        with self._write() as conn:
            for rec in records:
                self._insert(conn, case_id, rec)

    @staticmethod
    def _put(
        conn: sqlite3.Connection,
        table: str,
        key: dict[str, str | int],
        row: dict[str, str | int | None],
        digest: str,
    ) -> None:
        """INSERT OR IGNORE, then require the stored hash to equal ours (append-only)."""
        columns = {**key, **row, "record_hash": digest}
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        # `table` and column names are constants from this module, never user input.
        cur = conn.execute(
            f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})",  # noqa: S608
            tuple(columns.values()),
        )
        if cur.rowcount == 0:
            where = " AND ".join(f"{k} = ?" for k in key)
            found = conn.execute(
                f"SELECT record_hash FROM {table} WHERE {where}",  # noqa: S608
                tuple(key.values()),
            ).fetchone()
            if found is None or found[0] != digest:
                raise AppendOnlyViolation("record exists with different content")

    def _insert(self, conn: sqlite3.Connection, case_id: str, rec: AppendableRecord) -> None:
        digest = record_hash(rec)
        if isinstance(rec, Case):
            self._same_case(case_id, rec.case_id)
            self._put(
                conn,
                "cases",
                {"case_id": rec.case_id},
                {
                    "title": rec.title,
                    "entities": _dump_list(rec.entities),
                    "window_start": rec.window_start,
                    "window_end": rec.window_end,
                    "plant_tz": rec.plant_tz,
                    "created_at": rec.created_at,
                    "body": _json(rec),
                },
                digest,
            )
        elif isinstance(rec, Source):
            self._same_case(case_id, rec.case_id)
            cov = rec.coverage_period
            self._put(
                conn,
                "sources",
                {"case_id": case_id, "source_id": rec.source_id},
                {
                    "modality": rec.modality,
                    "sha256": rec.sha256,
                    "origin": rec.origin,
                    "ingested_at": rec.ingested_at,
                    "synthetic": int(rec.synthetic),
                    "mime": rec.mime,
                    "size": rec.size,
                    "held_reason": rec.held_reason,
                    "coverage_start": cov.start if cov else None,
                    "coverage_end": cov.end if cov else None,
                    "derived_from_sources": _dump_list(rec.derived_from_sources),
                    "body": _json(rec),
                },
                digest,
            )
        elif isinstance(rec, ClaimRecord):
            self._same_case(case_id, rec.case_id)
            vt = rec.temporal.valid_time
            start = getattr(vt, "start", None)
            end = getattr(vt, "end", None)
            self._put(
                conn,
                "claims",
                {"case_id": case_id, "claim_id": rec.claim_id},
                {
                    "label": rec.label,
                    "entity_key": rec.subject.entity_id,
                    "attribute": rec.attribute,
                    "valid_start": start,
                    "valid_end": end,
                    "claim_type": rec.claim_type,
                    "modality": rec.modality,
                    "body": _json(rec),
                },
                rec.record_hash,
            )
        elif isinstance(rec, ComparisonRecord):
            self._put(
                conn,
                "comparisons",
                {"case_id": case_id, "comparison_id": rec.comparison_id},
                {
                    "claim_a": rec.claim_a,
                    "claim_b": rec.claim_b,
                    "config_hash": rec.config_hash,
                    "outcome": rec.outcome,
                    "body": _json(rec),
                },
                digest,
            )
        elif isinstance(rec, ConflictRecord):
            self._put(
                conn,
                "conflicts",
                {"case_id": case_id, "conflict_id": rec.conflict_id},
                {"sides": _dump_list(rec.sides), "body": _json(rec)},
                digest,
            )
        elif isinstance(rec, Envelope):
            self._put(
                conn,
                "envelopes",
                {"case_id": case_id, "envelope_id": rec.envelope_id},
                {"machine": rec.machine, "series_id": rec.series_id, "body": _json(rec)},
                digest,
            )
        elif isinstance(rec, ReviewItem):
            self._put(
                conn,
                "review_items",
                {"case_id": case_id, "review_id": rec.review_id},
                {
                    "type": rec.type,
                    "claim_ids": _dump_list(rec.claim_ids),
                    "evidence_hash": rec.evidence_hash,
                    "opened_at": rec.opened_at,
                    "body": _json(rec),
                },
                digest,
            )
        else:  # ReviewEvent
            self._put(
                conn,
                "review_events",
                {"review_id": rec.review_id, "seq": rec.seq},
                {
                    "case_id": case_id,
                    "event_id": rec.event_id,
                    "kind": rec.kind,
                    "decision_id": rec.decision_id,
                    "at": rec.at,
                    "body": _json(rec),
                },
                digest,
            )

    @staticmethod
    def _same_case(expected: str, actual: str) -> None:
        if expected != actual:
            raise ValueError("record belongs to a different case")

    # --------------------------------------------------------------------- versions
    def put_version(self, version: CaseVersion, members: VersionMembers) -> None:
        with self._write() as conn:
            self._put_version(conn, version, members)

    @staticmethod
    def _put_version(
        conn: sqlite3.Connection, version: CaseVersion, members: VersionMembers
    ) -> None:
        row = conn.execute(
            "SELECT version, manifest_hash FROM versions WHERE case_id = ?"
            " ORDER BY version DESC LIMIT 1",
            (version.case_id,),
        ).fetchone()
        latest_v, latest_hash = (row[0], row[1]) if row else (0, None)
        if version.version != latest_v + 1:
            raise IntegrityError("version must be latest + 1")
        if version.parent_manifest_hash != latest_hash:
            raise IntegrityError("parent_manifest_hash does not chain to the latest version")
        wanted = (
            ("claim", "claims", "claim_id", members.claim_ids),
            ("comparison", "comparisons", "comparison_id", members.comparison_ids),
            ("conflict", "conflicts", "conflict_id", members.conflict_ids),
        )
        for _kind, table, col, ids in wanted:
            for rid in ids:
                found = conn.execute(
                    f"SELECT 1 FROM {table} WHERE case_id = ? AND {col} = ?",  # noqa: S608
                    (version.case_id, rid),
                ).fetchone()
                if found is None:
                    raise IntegrityError(f"version member {rid} was never appended")
        snapshot = _json(version).encode("utf-8")
        conn.execute(
            "INSERT INTO versions (case_id, version, parent_manifest_hash, manifest_hash,"
            " snapshot_sha256, config_hash, engine_sha, snapshot, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version.case_id,
                version.version,
                version.parent_manifest_hash,
                version.manifest_hash,
                hashlib.sha256(snapshot).hexdigest(),
                version.config_hash,
                version.engine_sha,
                snapshot,
                version.created_at,
            ),
        )
        for kind, _table, _col, ids in wanted:
            conn.executemany(
                "INSERT INTO version_claims (case_id, version, kind, record_id)"
                " VALUES (?, ?, ?, ?)",
                [(version.case_id, version.version, kind, rid) for rid in ids],
            )

    def get_version(self, case_id: str, version: int) -> CaseVersion | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT snapshot, snapshot_sha256 FROM versions WHERE case_id = ? AND version = ?",
                (case_id, version),
            ).fetchone()
        if row is None:
            return None
        snapshot: bytes = row[0]
        if hashlib.sha256(snapshot).hexdigest() != row[1]:
            raise IntegrityError("snapshot bytes do not match their stored sha256")
        return CaseVersion.model_validate_json(snapshot)

    def latest(self, case_id: str) -> CaseVersion | None:
        with self._read() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM versions WHERE case_id = ?", (case_id,)
            ).fetchone()
        return None if row is None or row[0] is None else self.get_version(case_id, int(row[0]))

    def load_claims(self, case_id: str, version: int) -> list[ClaimRecord]:
        with self._read() as conn:
            rows = conn.execute(
                "SELECT c.body FROM version_claims vc"
                " JOIN claims c ON c.case_id = vc.case_id AND c.claim_id = vc.record_id"
                " WHERE vc.case_id = ? AND vc.version = ? AND vc.kind = 'claim'"
                " ORDER BY COALESCE(c.valid_start, '9999'), c.claim_id",
                (case_id, version),
            ).fetchall()
        return [ClaimRecord.model_validate_json(r[0]) for r in rows]

    def review_events(self, case_id: str, review_id: str | None = None) -> list[ReviewEvent]:
        sql = "SELECT body FROM review_events WHERE case_id = ?"
        args: tuple[str, ...] = (case_id,)
        if review_id is not None:
            sql += " AND review_id = ?"
            args = (case_id, review_id)
        with self._read() as conn:
            rows = conn.execute(sql + " ORDER BY review_id, seq", args).fetchall()
        return [ReviewEvent.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------- decisions
    def commit_decision(
        self,
        case_id: str,
        expected_latest: int,
        decision: Decision,
        event: ReviewEvent,
        version: CaseVersion,
    ) -> Committed | Moved:
        """Short BEGIN IMMEDIATE re-check, then insert. 409 causes raise; a moved latest returns."""
        if decision.case_id != case_id or version.case_id != case_id:
            raise ValueError("decision and version must belong to the case")
        if event.review_id != decision.review_id or event.decision_id != decision.decision_id:
            raise ValueError("event does not match the decision")
        if event.kind != event_kind_for(decision.choice):
            raise ValueError("event kind does not match the decision choice")
        with self._write() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM versions WHERE case_id = ?", (case_id,)
            ).fetchone()
            latest = int(row[0]) if row and row[0] is not None else 0
            if latest != expected_latest:
                return Moved(latest=latest)
            item = conn.execute(
                "SELECT evidence_hash FROM review_items WHERE case_id = ? AND review_id = ?",
                (case_id, decision.review_id),
            ).fetchone()
            if item is None:
                raise ValueError("unknown review item")
            if item[0] != decision.shown_evidence_hash:
                raise EvidenceChanged("evidence changed since it was shown")
            if closes_item(decision.choice) and decision.supersedes is None:
                existing = conn.execute(
                    "SELECT d.decision_id FROM review_events e"
                    " JOIN decisions d ON d.case_id = e.case_id AND d.decision_id = e.decision_id"
                    " WHERE e.review_id = ? AND e.kind = ? AND d.choice_type != 'escalate'"
                    " ORDER BY e.seq LIMIT 1",
                    (decision.review_id, event.kind),
                ).fetchone()
                if existing is not None:
                    raise AlreadyDecided(existing[0])
            nxt = conn.execute(
                "SELECT COALESCE(MAX(seq) + 1, 0) FROM review_events WHERE review_id = ?",
                (decision.review_id,),
            ).fetchone()[0]
            if event.seq != nxt:
                raise ValueError("event seq must be the next sequence number for the item")
            self._put(
                conn,
                "decisions",
                {"case_id": case_id, "decision_id": decision.decision_id},
                {
                    "review_id": decision.review_id,
                    "choice_type": decision.choice.type,
                    "principal_iss": decision.principal.iss,
                    "principal_sub": decision.principal.sub,
                    "role_snapshot": decision.role_snapshot,
                    "base_version": decision.base_version,
                    "shown_evidence_hash": decision.shown_evidence_hash,
                    "supersedes": decision.supersedes,
                    "at": decision.at,
                    "body": _json(decision),
                },
                record_hash(decision),
            )
            self._insert(conn, case_id, event)
            self._put_version(conn, version, VersionMembers.from_records(version.records))
        return Committed(version=version.version, manifest_hash=version.manifest_hash)


def _dump_list(items: Sequence[str]) -> str:
    return json.dumps(list(items))
