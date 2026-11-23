"""Holdout gate (D-09, T-31). The holdout is run ONCE, from a clean tree, after the three hashes it
depends on (config, engine, lockfile) are on the remote, so nobody can tune after seeing it.

This module only decides whether a holdout run is allowed. It never runs one: `make eval-holdout`
is the only entry point, and it refuses unless every precondition below holds.
"""

from __future__ import annotations

import subprocess  # noqa: S404 (fixed git arguments, no shell)
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HOLDOUT_ENV = "TRACE_HOLDOUT_RUN"
"""Set to 1 by `make eval-holdout` only; `holdout`-marked tests are skipped without it."""
HOLDOUT_PATH_PART = "faults/holdout"
"""Seeds under this path belong to the holdout (never opened by dev code)."""

GitRunner = Callable[[list[str]], str]


def run_git(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


@dataclass(frozen=True)
class Precondition:
    name: str
    ok: bool
    detail: str


def tree_is_clean(git: GitRunner) -> Precondition:
    status = git(["status", "--porcelain"]).strip()
    return Precondition(
        "clean working tree", not status, "clean" if not status else "uncommitted changes"
    )


def hash_is_pushed(git: GitRunner, label: str, commit: str) -> Precondition:
    """`commit` (the commit that last changed the hashed input) is contained in a remote branch."""
    branches = git(["branch", "-r", "--contains", commit]).strip()
    return Precondition(
        f"{label} on the remote",
        bool(branches),
        branches.splitlines()[0].strip() if branches else "not contained in any remote branch",
    )


def check_holdout(git: GitRunner, hashed_inputs: dict[str, str]) -> list[Precondition]:
    """`hashed_inputs`: label (config, engine, lockfile) -> the commit that last touched it."""
    out = [tree_is_clean(git)]
    out.extend(
        hash_is_pushed(git, label, commit) for label, commit in sorted(hashed_inputs.items())
    )
    return out


def allowed(preconditions: list[Precondition]) -> bool:
    return all(p.ok for p in preconditions)
