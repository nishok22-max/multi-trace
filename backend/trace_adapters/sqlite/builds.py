"""BuildRepository: the mutable `builds` table (operational, not evidence).

One build in flight per case and one active build per `build_key` are enforced by the partial
unique indexes of migration 003; this class only translates the conflicts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trace_adapters.sqlite.store import connect
from trace_core.models.case import BuildStatus


class BuildInProgress(Exception):
    """Another build of this case is queued or running."""


def _status(row: sqlite3.Row | tuple[object, ...]) -> BuildStatus:
    build_id, case_id, status, version, heartbeat, stage_ms, counters = row
    return BuildStatus.model_validate(
        {
            "build_id": build_id,
            "case_id": case_id,
            "status": status,
            "version": version,
            "heartbeat_at": heartbeat,
            "stage_ms": json.loads(str(stage_ms)),
            "counters": json.loads(str(counters)),
        }
    )


_COLUMNS = "build_id, case_id, status, version, heartbeat_at, stage_ms, counters"


class BuildRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)

    def _exec(self, sql: str, args: tuple[object, ...] = ()) -> sqlite3.Cursor:
        conn = connect(self._path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(sql, args)
            conn.execute("COMMIT")
            return cur
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def get(self, build_id: str) -> BuildStatus | None:
        conn = connect(self._path)
        try:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM builds WHERE build_id = ?",  # noqa: S608
                (build_id,),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else _status(row)

    def active_for_key(self, build_key: str) -> BuildStatus | None:
        """A queued, running or done build with this key (idempotency)."""
        conn = connect(self._path)
        try:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM builds WHERE build_key = ?"  # noqa: S608
                " AND status IN ('queued','running','done') LIMIT 1",
                (build_key,),
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else _status(row)

    def in_flight(self, case_id: str) -> bool:
        """True while a build of this case is queued or running."""
        conn = connect(self._path)
        try:
            row = conn.execute(
                "SELECT 1 FROM builds WHERE case_id = ? AND status IN ('queued','running') LIMIT 1",
                (case_id,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    def stale_in_flight(self, before: str) -> list[str]:
        """Queued or running builds whose last heartbeat is older than `before`."""
        conn = connect(self._path)
        try:
            rows = conn.execute(
                "SELECT build_id FROM builds WHERE status IN ('queued','running')"
                " AND heartbeat_at < ? ORDER BY build_id",
                (before,),
            ).fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    def create(self, build_id: str, case_id: str, build_key: str, now: str) -> None:
        try:
            self._exec(
                "INSERT INTO builds (build_id, case_id, build_key, status, started_at,"
                " heartbeat_at) VALUES (?, ?, ?, 'queued', ?, ?)",
                (build_id, case_id, build_key, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise BuildInProgress from exc

    def mark_running(self, build_id: str, now: str) -> None:
        self._exec(
            "UPDATE builds SET status = 'running', heartbeat_at = ? WHERE build_id = ?"
            " AND status IN ('queued','running')",
            (now, build_id),
        )

    def heartbeat(self, build_id: str, now: str) -> None:
        self._exec(
            "UPDATE builds SET heartbeat_at = ? WHERE build_id = ? AND status = 'running'",
            (now, build_id),
        )

    def finish_ok(
        self,
        build_id: str,
        version: int,
        stage_ms: dict[str, int],
        counters: dict[str, int],
        now: str,
    ) -> None:
        self._exec(
            "UPDATE builds SET status = 'done', version = ?, stage_ms = ?, counters = ?,"
            " heartbeat_at = ?, finished_at = ? WHERE build_id = ?",
            (version, json.dumps(stage_ms), json.dumps(counters), now, now, build_id),
        )

    def finish_failed(self, build_id: str, status: str, error_code: str, now: str) -> None:
        self._exec(
            "UPDATE builds SET status = ?, error_code = ?, finished_at = ?"
            " WHERE build_id = ? AND status IN ('queued','running')",
            (status, error_code, now, build_id),
        )
