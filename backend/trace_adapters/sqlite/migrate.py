"""Forward-only SQL migrations. An applied file whose bytes later change is an integrity error."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from trace_core.errors import IntegrityError

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "sqlite"


def apply_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every numbered `*.sql` file not yet applied. Returns the names applied now."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, sha256 TEXT NOT NULL) STRICT"
    )
    applied = {
        name: sha for name, sha in conn.execute("SELECT name, sha256 FROM schema_migrations")
    }
    done: list[str] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        sql = path.read_text(encoding="utf-8")
        sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        if path.name in applied:
            if applied[path.name] != sha:
                raise IntegrityError(f"migration {path.name} changed after it was applied")
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nCOMMIT;")
            conn.execute(
                "INSERT INTO schema_migrations(name, sha256) VALUES (?, ?)", (path.name, sha)
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        done.append(path.name)
    return done
