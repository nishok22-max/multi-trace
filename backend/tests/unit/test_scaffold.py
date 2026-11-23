"""M0 scaffold tests: package imports, architecture rules, lockfiles, helpers, socket guard."""

from __future__ import annotations

import ast
import importlib
import json
import pkgutil
import re
import socket
import tomllib
from pathlib import Path

import pytest
import pytest_socket

from tools import check_no_mean, smoke

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
PACKAGES = ["trace_core", "trace_adapters", "trace_api", "trace_worker", "trace_eval", "tools"]
FORBIDDEN_CORE = {
    "sqlite3", "pypdfium2", "pytesseract", "PIL", "openai", "httpx",
    "requests", "socket", "subprocess", "pyarrow",
}  # fmt: skip


def _py_files(pkg: str) -> list[Path]:
    return sorted((BACKEND / pkg).rglob("*.py"))


@pytest.mark.parametrize("pkg", PACKAGES)
def test_packages_import(pkg: str) -> None:
    mod = importlib.import_module(pkg)
    if pkg == "trace_adapters":  # groq is never imported when modes are off
        skip = ("trace_adapters.groq",)
    else:
        skip = ()
    for info in pkgutil.walk_packages(mod.__path__, prefix=f"{pkg}."):
        if info.name.startswith(skip) or info.name in {"tools.task", "tools.smoke"}:
            continue
        importlib.import_module(info.name)


def test_trace_core_imports_no_forbidden_modules() -> None:
    bad: list[str] = []
    for path in _py_files("trace_core"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            bad += [f"{path.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN_CORE]
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
                bad.append(f"{path.name}: open()")
    assert not bad, bad


def test_worker_does_not_import_api() -> None:
    for path in _py_files("trace_worker"):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+trace_api", src, re.M), path.name


def test_check_no_mean_flags_pandas_paths() -> None:
    assert check_no_mean.check_source("df.mean()")
    assert check_no_mean.check_source("df.resample('1h')")
    assert check_no_mean.check_source("df.pivot_table(index='a')")
    assert check_no_mean.check_source("df.pivot_table(index='a', aggfunc='mean')")
    assert not check_no_mean.check_source("df.pivot_table(index='a', aggfunc='max')")
    assert check_no_mean.scan() == []


def test_smoke_rejects_network_fs_for_db() -> None:
    ok, _ = smoke.is_local_disk(Path(r"\\server\share\data"))
    assert not ok
    ok, _ = smoke.is_local_disk(Path(r"\\wsl$\Ubuntu\home\x\data"))
    assert not ok


def _norm(name: str) -> str:
    return (
        re.split(r"[\[<>=!~ ;@]", name, maxsplit=1)[0].lower().replace("_", "-").replace(".", "-")
    )


def test_lockfiles_in_sync() -> None:
    # uv.lock vs pyproject.toml (offline check)
    uv_lock = BACKEND / "uv.lock"
    assert uv_lock.is_file(), "backend/uv.lock missing: run `uv sync`"
    lock = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
    root = next(p for p in lock["package"] if p["name"] == "trace")
    locked = {_norm(d["name"]) for d in root.get("dependencies", [])}
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    wanted = {_norm(d) for d in project["project"]["dependencies"]}
    assert wanted <= locked, f"uv.lock is stale: {sorted(wanted - locked)}"

    # package-lock.json vs package.json
    fe = REPO / "frontend"
    assert (fe / "package-lock.json").is_file(), "frontend/package-lock.json missing"
    pkg = json.loads((fe / "package.json").read_text(encoding="utf-8"))
    plock = json.loads((fe / "package-lock.json").read_text(encoding="utf-8"))["packages"][""]
    for key in ("dependencies", "devDependencies"):
        assert pkg.get(key, {}) == plock.get(key, {}), f"package-lock.json stale ({key})"


def test_pytest_socket_blocks_network() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
