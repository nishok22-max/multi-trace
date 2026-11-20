"""Never-average gate (promise 1): AST check over trace_core and trace_adapters.

Flags `.mean(`, `.resample(`, `mean(`/`average(` calls, and `pivot_table(` without an
explicit non-mean `aggfunc`. The only allowed exception is trace_core/read/sensor.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("trace_core", "trace_adapters")
ALLOWED = {"trace_core/read/sensor.py"}
MEAN_NAMES = {"mean", "average", "avg", "nanmean"}


def _is_mean_aggfunc(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in MEAN_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in MEAN_NAMES
    if isinstance(node, ast.Name):
        return node.id in MEAN_NAMES
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return any(_is_mean_aggfunc(e) for e in node.elts)
    return True  # dicts, lambdas, anything dynamic: fail closed


def check_source(source: str, filename: str = "<string>") -> list[str]:
    """Return violation messages for one module's source text."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        where = f"{filename}:{node.lineno}"
        if name in MEAN_NAMES:
            problems.append(f"{where}: averaging call '{name}(' is banned")
        elif name == "resample":
            problems.append(f"{where}: '.resample(' is banned")
        elif name == "pivot_table":
            agg = next((k.value for k in node.keywords if k.arg == "aggfunc"), None)
            if agg is None or _is_mean_aggfunc(agg):
                problems.append(f"{where}: 'pivot_table(' needs an explicit non-mean aggfunc")
    return problems


def scan(root: Path = BACKEND) -> list[str]:
    problems: list[str] = []
    for d in SCAN_DIRS:
        for path in sorted((root / d).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in ALLOWED:
                continue
            problems.extend(check_source(path.read_text(encoding="utf-8"), rel))
    return problems


def main() -> int:
    problems = scan()
    for p in problems:
        print(p)
    print("check_no_mean: FAIL" if problems else "check_no_mean: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
