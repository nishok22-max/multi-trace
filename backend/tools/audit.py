"""`make audit` (D-11, T-37): a one-shot security and hygiene audit whose result is written to the
freeze notes (`docs/MVP_FREEZE_NOTES.md`). Offline by default; the checks that need the network
(`npm audit`, `pip-audit`) run only with `TRACE_AUDIT_ONLINE=1` and are otherwise recorded as
SKIPPED with the reason, never as passed.

    python -m tools.audit            # offline checks, writes the notes
    python -m tools.audit --full     # also `make check` and `make e2e`
    TRACE_AUDIT_ONLINE=1 python -m tools.audit

A finding is `critical`, `high`, `medium` or `low`. The audit FAILS on any critical or high
finding that has no waiver in `docs/MVP_FREEZE_NOTES.md` (the "Waivers" section).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # noqa: S404 (fixed argument lists, no shell)
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
NOTES = REPO / "docs" / "MVP_FREEZE_NOTES.md"
SECRET_PATTERNS = {
    "Groq-style key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}
SECRET_ALLOWED_DIRS = ("backend/tests/", "docs/")
"""Tests hold deliberate sentinels; docs describe the patterns."""
MUST_BE_UNTRACKED = (".env", "seed/credentials.local.txt")
LOCKED_RUNTIME_DEPS = ("fastapi", "pydantic", "argon2-cffi", "pypdfium2")


@dataclass
class Check:
    name: str
    status: str  # passed | failed | skipped
    detail: str
    severity: str = "low"
    items: list[str] = field(default_factory=list)


def _run(args: list[str], cwd: Path = BACKEND, timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603
        args, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def _py(*args: str) -> tuple[int, str]:
    return _run([sys.executable, "-m", *args])


def tracked_files() -> list[str]:
    code, out = _run(["git", "ls-files"], cwd=REPO)
    return out.splitlines() if code == 0 else []


def scan_secrets(files: list[str], root: Path = REPO) -> list[str]:
    """`path: pattern name` for every secret-shaped string in a tracked text file."""
    hits: list[str] = []
    for rel in files:
        if rel.startswith(SECRET_ALLOWED_DIRS) or rel.endswith(
            (".png", ".pdf", ".parquet", ".ttf")
        ):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                hits.append(f"{rel}: {label}")
    return hits


def check_secrets() -> Check:
    files = tracked_files()
    tracked_forbidden = [f for f in files if f in MUST_BE_UNTRACKED or f.endswith(".db")]
    hits = scan_secrets(files)
    bad = [*hits, *(f"{f}: must not be tracked" for f in tracked_forbidden)]
    return Check(
        "secrets in tracked files",
        "failed" if bad else "passed",
        f"{len(files)} tracked files scanned" + (f"; {len(bad)} finding(s)" if bad else ""),
        severity="critical",
        items=bad,
    )


def check_command(name: str, args: list[str], severity: str = "high") -> Check:
    code, out = _py(*args)
    last = (out.strip().splitlines() or [""])[-1]
    return Check(name, "passed" if code == 0 else "failed", last[:200], severity=severity)


def check_lockfiles_and_defaults() -> Check:
    code, out = _py(
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/unit/test_scaffold.py",
        "-k",
        "lockfiles_in_sync or dockerignore_excludes_secrets or groq_disabled or loopback_only",
    )
    return Check(
        "lockfiles in sync; secrets ignored; AI off by default; loopback ports",
        "passed" if code == 0 else "failed",
        (out.strip().splitlines() or [""])[-1][:200],
        severity="high",
    )


def check_online(name: str, args: list[str], cwd: Path, severity_of: str) -> Check:
    if os.environ.get("TRACE_AUDIT_ONLINE") != "1":
        return Check(
            name,
            "skipped",
            "offline: this scan contacts a package registry; run with TRACE_AUDIT_ONLINE=1",
        )
    exe = shutil.which(args[0])
    if not exe:
        return Check(name, "skipped", f"{args[0]} is not installed")
    code, out = _run([exe, *args[1:]], cwd=cwd, timeout=600)
    found = len(re.findall(severity_of, out, re.IGNORECASE))
    return Check(
        name,
        "passed" if found == 0 and code in (0, 1) else "failed",
        f"{found} critical/high advisories",
        severity="high",
    )


def waived(notes: str) -> set[str]:
    """Check names listed under the Waivers heading (one per line, `- <name>: <reason>`)."""
    out: set[str] = set()
    in_section = False
    for line in notes.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower() == "## waivers"
        elif in_section and line.startswith("- ") and ":" in line:
            out.add(line[2:].split(":", 1)[0].strip())
    return out


def evaluate(checks: list[Check], existing_notes: str = "") -> list[Check]:
    """The checks that block the freeze: failed, critical or high, and not waived."""
    allowed = waived(existing_notes)
    return [
        c
        for c in checks
        if c.status == "failed" and c.severity in ("critical", "high") and c.name not in allowed
    ]


def hashes() -> dict[str, str]:
    sys.path.insert(0, str(BACKEND))
    from trace_adapters.config_loader import load_config_bundle
    from trace_core.ids import config_hash
    from trace_worker.env import engine_sha, lockfile_hash

    _, commit = _run(["git", "rev-parse", "HEAD"], cwd=REPO)
    _, dirty = _run(["git", "status", "--porcelain"], cwd=REPO)
    return {
        "commit": commit.strip(),
        "tree": "clean" if not dirty.strip() else "uncommitted changes present",
        "config_hash": config_hash(load_config_bundle()),
        "engine_sha": engine_sha(),
        "lockfile_hash": lockfile_hash(),
    }


def render(checks: list[Check], info: dict[str, str], blocking: list[Check], waivers: str) -> str:
    rows = "\n".join(
        f"| {c.name} | {c.status.upper()} | {c.severity} | {c.detail} |" for c in checks
    )
    findings = "\n".join(f"- {c.name}: {item}" for c in checks for item in c.items) or "- none"
    verdict = (
        "BLOCKED: " + ", ".join(c.name for c in blocking)
        if blocking
        else "no unwaived critical or high finding"
    )
    return f"""# MVP freeze notes

Generated by `make audit` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Do not edit the tables by
hand; edit only the **Waivers** section.

## Hashes at the freeze

| Item | Value |
|---|---|
| commit | `{info["commit"]}` |
| working tree | {info["tree"]} |
| config_hash | `{info["config_hash"]}` |
| engine_sha | `{info["engine_sha"]}` |
| lockfile_hash | `{info["lockfile_hash"]}` |

The three hashes must be on the remote before `make eval-holdout` is allowed
(`trace_eval.holdout.check_holdout`). Pushing them is the maintainers' decision.

## Audit results

| Check | Result | Severity | Detail |
|---|---|---|---|
{rows}

**Verdict:** {verdict}.

### Findings

{findings}

## Waivers

{waivers}
"""


def existing_waivers() -> str:
    if NOTES.is_file():
        text = NOTES.read_text(encoding="utf-8")
        if "## Waivers" in text:
            return text.split("## Waivers", 1)[1].strip()
    return "- none: no finding is waived."


def main(argv: list[str]) -> int:
    full = "--full" in argv
    checks = [
        check_secrets(),
        check_lockfiles_and_defaults(),
        check_command(
            "import contracts (core pure, layers, API never decodes)", ["tools.task", "imports"]
        ),
        check_command("never-average gate", ["tools.check_no_mean"], severity="critical"),
        check_command("frozen contracts match the code", ["tools.task", "contracts-check"]),
        check_online(
            "npm audit (frontend)",
            ["npm", "audit", "--audit-level=high"],
            REPO / "frontend",
            r"\b(critical|high)\b",
        ),
        check_online("pip-audit (backend)", ["pip-audit", "--strict"], BACKEND, r"\bvulnerab"),
    ]
    if full:
        checks.append(
            check_command(
                "make check (lint, types, imports, nomean, contracts, tests)",
                ["tools.task", "check"],
                severity="high",
            )
        )
        checks.append(
            check_command(
                "make e2e (Playwright under the enforcing CSP)",
                ["tools.task", "e2e"],
                severity="high",
            )
        )
    else:
        checks.append(Check("make check and make e2e", "skipped", "not run here; pass --full"))
    waivers = existing_waivers()
    blocking = evaluate(checks, "## Waivers\n" + waivers)
    NOTES.write_text(render(checks, hashes(), blocking, waivers), encoding="utf-8", newline="\n")
    print(json.dumps({"notes": str(NOTES), "blocking": [c.name for c in blocking]}))
    for c in checks:
        print(f"{c.status.upper():8} {c.name}: {c.detail}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
