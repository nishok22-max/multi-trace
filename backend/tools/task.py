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
    "golden": _stub("M3"),
    "golden-bless": _stub("M3"),
    "golden-randseed": _stub("M3"),
    "props": _stub("M1"),
    "hostile": _stub("M3"),
    "authz": _stub("M3"),
    "check-perf": _stub("M3"),
    "e2e": _stub("M4"),
    "seed": _stub("M3"),
    "seed-gen": _stub("M3"),
    "record-cache": _stub("M3"),
    "demo": _stub("M3"),
    "replay-verify": _stub("M3"),
    "eval-dev": _stub("M5"),
    "eval-holdout": _stub("M6"),
    "audit": _stub("M5"),
    "anchor": _stub("M6"),
    "run-native": _stub("M2"),
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in TASKS:
        print("usage: python -m tools.task <name>\ntasks: " + ", ".join(TASKS))
        return 2
    return TASKS[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
