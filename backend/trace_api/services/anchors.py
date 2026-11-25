"""Anchor roots (D-04, N-2): `anchors/demo_roots.txt` lists `<utc time> <case> v<N> <manifest_hash>`
lines. A root listed there AND pushed to the remote cannot be rewritten by whoever holds the
database; the push is checked by the rehearsal (`tools/rehearse.py`), not by the API."""

from __future__ import annotations

from pathlib import Path

HEX = set("0123456789abcdef")
SHA256_HEX_LEN = 4 * 16  # a sha256 manifest hash in hex


def anchored_roots(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    roots: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and len(parts[-1]) == SHA256_HEX_LEN and set(parts[-1]) <= HEX:
            roots.add(parts[-1])
    return roots


def is_anchored(path: Path, manifest_hash: str) -> bool:
    return manifest_hash in anchored_roots(path)
