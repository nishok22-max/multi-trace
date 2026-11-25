"""Pre-demo rehearsal against HARDENING section 6 (h33). Every item that a machine can check is
checked and written to `docs/MVP_REHEARSAL.md`; the items only a person can do are listed as
MANUAL and are never reported as done.

    python -m tools.rehearse              # fast checks
    python -m tools.rehearse --full       # also the goldens, hostile corpus and Playwright
"""

from __future__ import annotations

import json
import subprocess  # noqa: S404 (fixed arguments, no shell)
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
OUT = REPO / "docs" / "MVP_REHEARSAL.md"


@dataclass
class Item:
    text: str
    status: str  # ok | FAIL | PENDING | MANUAL | not run
    detail: str


def _git(*args: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return out.stdout.strip()


def on_remote(commit: str) -> str:
    branches = _git("branch", "-r", "--contains", commit) if commit else ""
    return branches.splitlines()[0].strip() if branches else ""


def _task(name: str) -> tuple[bool, str]:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tools.task", name],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode == 0, last[:160]


def check_h0() -> Item:
    report = REPO / "data" / "h0_report.json"
    case = (BACKEND / "config" / "case.yaml").read_text(encoding="utf-8")
    decided = "h0_decision: " in case and "h0_decision: null" not in case
    ok = report.is_file() and decided
    return Item("h0 reality check done and its decision pinned", "ok" if ok else "FAIL",
                "data/h0_report.json present, decision in config/case.yaml" if ok else "report or decision missing")  # fmt: skip


def check_quiet_days() -> Item:
    import sqlite3

    problems: list[str] = []
    checked = 0
    for db in sorted((REPO / "data").glob("**/trace.db")):
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            for (body,) in conn.execute("SELECT body FROM envelopes"):
                env = json.loads(body)
                checked += 1
                if env["n"] < 19 and env["pooled"] == "none":
                    problems.append(f"{env['machine']} n={env['n']} not labelled as pooled")
        finally:
            conn.close()
    if not checked:
        return Item("quiet-day counts measured", "PENDING", "no built case under data/")
    return Item("quiet-day counts measured (n >= 19 or labelled pooled)", "FAIL" if problems else "ok",
                "; ".join(problems) or f"{checked} envelope(s) checked")  # fmt: skip


def check_holdout_report() -> Item:
    path = REPO / "data" / "eval_report_holdout.json"
    if not path.is_file():
        return Item("config hash pushed BEFORE the holdout run; report shows the commit",
                    "PENDING", "the holdout has not been run")  # fmt: skip
    extras = json.loads(path.with_name(path.name + ".extras.json").read_text(encoding="utf-8"))
    git = extras.get("git", {})
    missing = [k for k in ("config_commit", "engine_commit", "lockfile_commit") if not git.get(k)]
    if missing:
        return Item("config hash pushed before the holdout run", "FAIL", f"report lacks {missing}")
    unpushed = [
        k for k in ("config_commit", "engine_commit", "lockfile_commit") if not on_remote(git[k])
    ]
    return Item("config hash pushed BEFORE the holdout run; report shows the commit",
                "FAIL" if unpushed else "ok",
                f"not on the remote: {unpushed}" if unpushed else "config, engine and lockfile commits are on the remote")  # fmt: skip


def check_anchors() -> Item:
    path = REPO / "anchors" / "demo_roots.txt"
    if not path.is_file():
        return Item("anchors/demo_roots.txt pushed; roots visible in the UI", "PENDING", "no anchor file: run `make anchor`")  # fmt: skip
    commit = _git("log", "-1", "--format=%H", "--", "anchors/demo_roots.txt")
    if not commit:
        return Item("anchors/demo_roots.txt pushed", "FAIL", "the anchor file is not committed")
    dirty = _git("status", "--porcelain", "--", "anchors/demo_roots.txt")
    remote = on_remote(commit)
    ok = bool(remote) and not dirty
    return Item("anchors/demo_roots.txt pushed to the remote; roots visible in the UI",
                "ok" if ok else "FAIL",
                f"on {remote}" if ok else "committed locally only or modified: push it")  # fmt: skip


def check_judge_card() -> Item:
    creds = REPO / "seed" / "credentials.local.txt"
    ok = creds.is_file() and any(
        line.startswith("judge\t") for line in creds.read_text(encoding="utf-8").splitlines()
    )
    return Item("judge account created (card to be printed by hand)", "ok" if ok else "PENDING",
                "judge persona exists in seed/credentials.local.txt" if ok else "run `python -m tools.seed_users`")  # fmt: skip


def run(full: bool) -> list[Item]:
    items = [check_h0(), check_quiet_days()]
    for text, task in (
        ("goldens for Demos 0-6 green", "golden"),
        ("hostile corpus passes", "hostile"),
        ("Playwright passes under the enforcing CSP", "e2e"),
    ):
        if full:
            ok, last = _task(task)
            items.append(Item(text, "ok" if ok else "FAIL", last))
        else:
            items.append(Item(text, "not run", "pass --full"))
    items += [check_holdout_report(), check_anchors(), check_judge_card()]
    items += [
        Item("two laptops with pre-built cases, no network needed", "MANUAL", "a person must do this"),
        Item("recorded backup video", "MANUAL", "a person must record it"),
        Item("log out between personas; 'signed in as' visible", "MANUAL", "the header shows it; the rehearsal must use it"),
    ]  # fmt: skip
    return items


def render(items: list[Item]) -> str:
    rows = "\n".join(f"| {i.text} | {i.status} | {i.detail} |" for i in items)
    open_items = [i.text for i in items if i.status in ("FAIL", "PENDING", "MANUAL", "not run")]
    return f"""# MVP rehearsal (HARDENING section 6)

Generated by `python -m tools.rehearse` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.

| Pre-demo item | Status | Detail |
|---|---|---|
{rows}

**Open items:** {len(open_items)}. {"; ".join(open_items) if open_items else "none"}.
"""


def main(argv: Sequence[str]) -> int:
    items = run("--full" in argv)
    OUT.write_text(render(items), encoding="utf-8", newline="\n")
    for i in items:
        print(f"{i.status:8} {i.text}: {i.detail}")
    return 1 if any(i.status == "FAIL" for i in items) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
