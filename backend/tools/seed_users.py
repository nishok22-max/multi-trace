"""Seed personas (TEST_PLAN 1.5): one user per role plus the judge persona, with passwords generated
per run. The passwords go to `seed/credentials.local.txt` (git- and docker-ignored) and are NEVER
printed or logged; tests read them from that file or from a fixture, never from source.

    python -m tools.seed_users [--data-dir data]
"""

from __future__ import annotations

import secrets
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CREDENTIALS = REPO / "seed" / "credentials.local.txt"
PERSONAS = (
    ("viewer1", "viewer"),
    ("reviewer1", "reviewer"),
    ("reviewer2", "reviewer"),
    ("senior1", "senior_reviewer"),
    ("ingestor1", "ingestor"),
    ("evaluator1", "evaluator"),
    ("judge", "senior_reviewer"),
)


def seed_users(data_dir: Path, credentials: Path = CREDENTIALS) -> list[str]:
    """Create the missing personas; returns the usernames created. Existing users keep their
    passwords (the credentials file is appended, never rewritten)."""
    from trace_adapters.clock import SystemClock
    from trace_adapters.sqlite.store import SqliteClaimStore
    from trace_api.security.sessions import AuthRepository

    data_dir.mkdir(parents=True, exist_ok=True)
    SqliteClaimStore(data_dir / "trace.db")  # migrations
    repo = AuthRepository(data_dir / "trace.db", SystemClock())
    created: list[str] = []
    lines: list[str] = []
    for name, role in PERSONAS:
        password = secrets.token_urlsafe(14)
        try:
            repo.create_user(f"u-{name}", name, name.title(), role, password)  # type: ignore[arg-type]
        except sqlite3.IntegrityError:
            pass  # the persona exists already; its password is not changed
        else:
            created.append(name)
            lines.append(f"{name}\t{role}\t{password}")
    if lines:
        credentials.parent.mkdir(parents=True, exist_ok=True)
        with credentials.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    return created


def main(argv: Sequence[str]) -> int:
    data_dir = Path(argv[argv.index("--data-dir") + 1]) if "--data-dir" in argv else REPO / "data"
    created = seed_users(data_dir)
    print(f"created {len(created)} persona(s): {', '.join(created) or 'none (all exist)'}")
    print(f"passwords are in {CREDENTIALS.relative_to(REPO)} (git-ignored); they are not printed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
