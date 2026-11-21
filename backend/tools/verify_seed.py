"""verify_seed: the committed seed bytes must match seed/SHA256SUMS (no generation here)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "seed"


def verify(seed: Path = SEED) -> list[str]:
    sums = seed / "SHA256SUMS"
    if not sums.is_file():
        return ["seed/SHA256SUMS is missing"]
    problems: list[str] = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, _, name = line.partition("  ")
        path = seed / name
        if not path.is_file():
            problems.append(f"{name}: missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"{name}: sha256 mismatch")
    return problems


def main() -> int:
    problems = verify()
    for problem in problems:
        print("verify_seed:", problem)
    print("verify_seed: ok" if not problems else "verify_seed: FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
