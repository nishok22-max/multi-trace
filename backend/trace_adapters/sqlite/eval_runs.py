"""EvalRunRepository: the mutable `eval_runs` table (operational, not evidence). One run in
flight is enforced by the partial unique index of migration 005; this class translates it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from trace_adapters.sqlite.store import connect


class EvalInProgress(Exception):
    """Another evaluation run is already running."""


class EvalRunRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)

    def _exec(self, sql: str, args: tuple[object, ...] = ()) -> None:
        conn = connect(self._path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(sql, args)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def start(self, run_id: str, now: str) -> None:
        try:
            self._exec(
                "INSERT INTO eval_runs (run_id, status, started_at) VALUES (?, 'running', ?)",
                (run_id, now),
            )
        except sqlite3.IntegrityError as exc:
            raise EvalInProgress from exc

    def finish(self, run_id: str, status: str, now: str, error_code: str | None = None) -> None:
        self._exec(
            "UPDATE eval_runs SET status = ?, finished_at = ?, error_code = ? WHERE run_id = ?"
            " AND status = 'running'",
            (status, now, error_code, run_id),
        )

    def get(self, run_id: str) -> tuple[str, str | None] | None:
        conn = connect(self._path)
        try:
            row = conn.execute(
                "SELECT status, error_code FROM eval_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        return None if row is None else (row[0], row[1])
