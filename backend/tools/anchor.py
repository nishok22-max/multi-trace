"""`make anchor` (D-04, N-2): record the latest manifest root of every case in
`anchors/demo_roots.txt`, so a root can be compared with a copy that lives off the serving box.

    python -m tools.anchor               # write the roots and commit them LOCALLY
    python -m tools.anchor --push        # ... and push the current branch (asks nothing: you chose)

Pushing makes the roots impossible to rewrite from the machine that holds the database, which is
the point. It is never done unless `--push` is given. The API shows whether a root is listed
(`X-Manifest-Anchored` on the integrity answer); that it was PUSHED is checked by the rehearsal.
"""

from __future__ import annotations

import sqlite3
import subprocess  # noqa: S404 (fixed git arguments, no shell)
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ANCHORS = REPO / "anchors" / "demo_roots.txt"
HEADER = "# <utc time> <case> v<version> <manifest_hash> (append-only; push before the demo)\n"


def databases(data_root: Path) -> list[Path]:
    found = [data_root / "trace.db", *sorted(data_root.glob("*/trace.db"))]
    return [p for p in found if p.is_file()]


def latest_roots(db: Path) -> list[tuple[str, int, str]]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT v.case_id, v.version, v.manifest_hash FROM versions v"
            " WHERE v.version = (SELECT MAX(version) FROM versions WHERE case_id = v.case_id)"
            " ORDER BY v.case_id"
        ).fetchall()
    finally:
        conn.close()
    return [(str(c), int(v), str(h)) for c, v, h in rows]


def append_roots(
    path: Path, roots: Sequence[tuple[str, int, str]], now: datetime | None = None
) -> list[str]:
    """Append the roots not already listed. Existing lines are never rewritten."""
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = path.read_text(encoding="utf-8") if path.is_file() else HEADER
    added = [
        f"{stamp} {case} v{version} {root}" for case, version, root in roots if root not in existing
    ]
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(existing + "\n".join(added) + "\n", encoding="utf-8", newline="\n")
    return added


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout


def commit(path: Path, count: int) -> bool:
    rel = path.relative_to(REPO).as_posix()
    _git("add", "--", rel)
    if not _git("diff", "--cached", "--name-only", "--", rel).strip():
        return False
    _git("commit", "-m", f"Anchor {count} manifest root(s)", "--", rel)
    return True


def main(argv: Sequence[str]) -> int:
    push = "--push" in argv
    roots: list[tuple[str, int, str]] = []
    for db in databases(REPO / "data"):
        roots.extend(latest_roots(db))
    if not roots:
        print("no built versions found under data/: build a case first")
        return 1
    added = append_roots(ANCHORS, roots)
    for line in added:
        print("anchored", line)
    if not added:
        print("every root is already anchored")
    if added and commit(ANCHORS, len(added)):
        print("committed locally")
    if push:
        _git("push")
        print("pushed")
    else:
        print("NOT pushed: the anchor protects nothing until it is on the remote (use --push)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
