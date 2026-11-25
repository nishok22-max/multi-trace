"""Task dispatcher: `uv run python -m tools.task <name>` (run from backend/).

The Makefile is only thin wrappers around this. Works from PowerShell without make.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
BIN = Path(sys.executable).parent


def _run(cmd: list[str], cwd: Path = BACKEND) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=False).returncode  # noqa: S603


def _npm(*args: str) -> int:
    npm = shutil.which("npm")
    if not npm:
        print("npm not found (install Node 20)")
        return 127
    return _run([npm, *args], cwd=FRONTEND)


def _frontend_ready() -> bool:
    if not (FRONTEND / "node_modules").is_dir():
        print("frontend/node_modules missing: run `npm ci --ignore-scripts` in frontend/ first")
        return False
    return True


def _py(*args: str) -> int:
    return _run([sys.executable, "-m", *args])


def setup() -> int:
    rc = _run(["uv", "sync"])
    rc = rc or _npm("ci", "--ignore-scripts")
    if (REPO / ".git").exists():
        rc = rc or _py("pre_commit", "install")
        rc = rc or _run(["git", "config", "core.longpaths", "true"], cwd=REPO)
    else:
        print("not a git repository: skipped pre-commit install and core.longpaths")
    return rc


def smoke_native() -> int:
    return _py("tools.smoke")


def lint() -> int:
    rc = _py("ruff", "check", ".")
    rc = _py("ruff", "format", "--check", ".") or rc
    if not _frontend_ready():
        return 1
    return _npm("run", "lint") or rc


def type_() -> int:
    rc = _py("mypy")
    if not _frontend_ready():
        return 1
    return _npm("run", "typecheck") or rc


def imports() -> int:
    exe = shutil.which("lint-imports", path=str(BIN))
    if not exe:
        print("lint-imports not found: run `uv sync`")
        return 127
    return _run([exe, "--config", str(REPO / ".importlinter")])


def nomean() -> int:
    return _py("tools.check_no_mean")


def contracts() -> int:
    return _py("tools.export_contracts")


def contracts_check() -> int:
    return _py("tools.export_contracts", "--check")


def demo_skeleton() -> int:
    return _py("tools.demo_skeleton")


def h0() -> int:
    return _py("tools.h0_reality")


def test_fast() -> int:
    return _py("pytest", "-q", "-m", "not holdout and not perf and not e2e and not slow")


def test() -> int:
    return _py("pytest", "-q", "-m", "not holdout and not perf and not e2e")


def check() -> int:
    failed = []
    for name, fn in (
        ("lint", lint),
        ("type", type_),
        ("imports", imports),
        ("nomean", nomean),
        ("contracts-check", contracts_check),
        ("test-fast", test_fast),
    ):
        print(f"\n=== {name} ===", flush=True)
        if fn() != 0:
            failed.append(name)
    print("\ncheck: FAIL (" + ", ".join(failed) + ")" if failed else "\ncheck: green")
    return 1 if failed else 0


def _pytest(*args: str, env: dict[str, str] | None = None) -> int:
    return _py("pytest", "-q", *args) if env is None else _run_env(env, "pytest", "-q", *args)


def _run_env(extra: dict[str, str], *args: str) -> int:
    import os

    previous = {k: os.environ.get(k) for k in extra}
    os.environ.update(extra)
    try:
        return _py(*args)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def golden() -> int:
    return _pytest("tests/golden")


def golden_randseed() -> int:
    """Goldens must not depend on the hash seed (determinism, promise 8)."""
    return _pytest("tests/golden", env={"PYTHONHASHSEED": "12345"})


def golden_bless() -> int:
    """Rewrites the goldens. Only with CONFIRM=1, and only while the conformal oracle is green."""
    import os

    if os.environ.get("CONFIRM") != "1":
        print("refusing: set CONFIRM=1 (the diff must be explained in the PR)")
        return 2
    if _pytest("tests/golden/test_conformal_oracle.py") != 0:
        print("refusing: the conformal oracle test is not green")
        return 1
    return _pytest("tests/golden", env={"TRACE_GOLDEN_BLESS": "1"})


def props() -> int:
    return _pytest("tests/properties", "tests/unit/engine", "-k", "prop or properties")


def hostile() -> int:
    return _pytest("tests/hostile_corpus", "tests/unit/api/test_upload_security.py")


def authz() -> int:
    return _pytest(
        "tests/unit/api/test_auth.py",
        "tests/unit/api/test_decisions_api.py",
        "tests/unit/api/test_sources_api.py",
    )


def eval_dev() -> int:
    """Dev-set evaluation: the protocol tests, then a dev run written to data/eval_report.json.
    The holdout never runs here."""
    rc = _pytest("tests/eval", "-m", "not holdout")
    out = REPO / "data" / "eval_report.json"
    return rc or _py("trace_eval.runner", "--out", str(out))


def eval_holdout() -> int:
    """The one-shot holdout run. Refuses unless the tree is clean and the config, engine and
    lockfile hashes are on the remote; it never pushes anything itself."""
    from trace_eval.holdout import HOLDOUT_ENV, allowed, check_holdout, run_git

    def git(args: list[str]) -> str:
        return run_git(args, REPO)

    last = {
        "config": "backend/config",
        "engine": "backend/trace_core",
        "lockfile": "backend/uv.lock",
    }
    inputs = {
        label: git(["log", "-1", "--format=%H", "--", path]).strip() for label, path in last.items()
    }
    pre = check_holdout(git, {k: v for k, v in inputs.items() if v})
    for item in pre:
        print(f"{'ok  ' if item.ok else 'FAIL'} {item.name}: {item.detail}")
    if not allowed(pre):
        print("refusing: the holdout may run only from a clean tree with the hashes pushed")
        return 2
    return _pytest("tests/eval", "-m", "holdout", env={HOLDOUT_ENV: "1"})


def audit() -> int:
    """One-shot audit; results go to docs/MVP_FREEZE_NOTES.md (offline by default)."""
    return _py("tools.audit")


def e2e() -> int:
    """Playwright specs against the real app: build the frontend, then run them."""
    if not _frontend_ready():
        return 1
    return _npm("run", "build") or _npm("run", "e2e")


def seed() -> int:
    """Seed the demo case into data/skeleton (idempotent) and print its id."""
    return _py("tools.seed_build")


def replay_verify() -> int:
    """Rebuild every stored version and compare the manifest hashes (native or image)."""
    return _py("tools.replay_verify")


def anchor() -> int:
    """Write the latest manifest roots to anchors/demo_roots.txt and commit them LOCALLY. Pushing
    is a separate, deliberate step: `python -m tools.anchor --push`."""
    return _py("tools.anchor")


def run_native() -> int:
    """Serve the built app on 127.0.0.1:8000 (real sessions: create users with `seed-users`)."""
    return _py("uvicorn", "trace_api.main:app", "--host", "127.0.0.1", "--port", "8000")


def rehearse() -> int:
    return _py("tools.rehearse")


def slide_numbers() -> int:
    return _py("tools.slide_numbers")


def perf_report() -> int:
    return _py("tools.perf_report")


def seed_users() -> int:
    return _py("tools.seed_users")


def check_perf() -> int:
    return _pytest("tests/perf", "-m", "perf")


def _stub(milestone: str) -> Callable[[], int]:
    def run() -> int:
        print(f"not implemented until {milestone}")
        return 0

    return run


TASKS: dict[str, Callable[[], int]] = {
    "setup": setup,
    "smoke-native": smoke_native,
    "lint": lint,
    "type": type_,
    "imports": imports,
    "nomean": nomean,
    "test-fast": test_fast,
    "test": test,
    "check": check,
    # Stubs (IMPLEMENTATION_PLAN B.2)
    "h0": h0,
    "demo-skeleton": demo_skeleton,
    "contracts": contracts,
    "contracts-check": contracts_check,
    "golden": golden,
    "golden-bless": golden_bless,
    "golden-randseed": golden_randseed,
    "props": props,
    "hostile": hostile,
    "authz": authz,
    "check-perf": check_perf,
    "e2e": e2e,
    "seed": seed,
    "seed-gen": _stub("M3"),
    "record-cache": _stub("M3"),
    "demo": demo_skeleton,
    "replay-verify": replay_verify,
    "eval-dev": eval_dev,
    "eval-holdout": eval_holdout,
    "audit": audit,
    "anchor": anchor,
    "run-native": run_native,
    "rehearse": rehearse,
    "slide-numbers": slide_numbers,
    "perf-report": perf_report,
    "seed-users": seed_users,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in TASKS:
        print("usage: python -m tools.task <name>\ntasks: " + ", ".join(TASKS))
        return 2
    return TASKS[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
