"""`make replay-verify` (D-11): rebuild every stored version from its stored artifacts and compare the
manifest hash. Run natively on Windows and in the image; the hashes must be the same everywhere
(the manifest does not depend on the machine, the clock or the OS).

    python -m tools.replay_verify [data_dir ...]      # default: data/ and data/*/
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def stored_versions(db: Path) -> list[tuple[str, int, str]]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT case_id, version, manifest_hash FROM versions ORDER BY case_id, version"
        ).fetchall()
    finally:
        conn.close()
    return [(str(c), int(v), str(h)) for c, v, h in rows]


def verify_dir(data_dir: Path) -> list[tuple[str, int, str, str]]:
    """(case, version, stored hash, rebuilt hash) for every stored version."""
    from trace_worker.build_runner import BuildPaths
    from trace_worker.replay import replay_manifest

    paths = BuildPaths(
        db=str(data_dir / "trace.db"),
        blobs=str(data_dir / "blobs"),
        derived=str(data_dir / "derived"),
    )
    return [
        (case, version, stored, replay_manifest(paths, case, version))
        for case, version, stored in stored_versions(data_dir / "trace.db")
    ]


def main(argv: Sequence[str]) -> int:
    dirs = [Path(a) for a in argv] or [
        d for d in (REPO / "data", *sorted((REPO / "data").glob("*"))) if (d / "trace.db").is_file()
    ]
    if not dirs:
        print("no data directory with a trace.db: build a case first")
        return 1
    bad = 0
    for data_dir in dirs:
        for case, version, stored, rebuilt in verify_dir(data_dir):
            ok = stored == rebuilt
            bad += 0 if ok else 1
            print(f"{'ok  ' if ok else 'FAIL'} {data_dir.name}/{case} v{version} {stored[:16]}")
    print("replay-verify: FAIL" if bad else "replay-verify: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
