"""Golden files pin COMPUTED values (promise 8): a scenario's outputs are produced by the engine
and compared with the stored JSON. Nothing in a golden is typed by hand.

Blessing (`make golden-bless CONFIRM=1`) rewrites the files; the diff must be explained in the PR,
and the conformal oracle test must be green first (tools/task.py enforces both)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).resolve().parent / "files"


def _six(value: Any) -> Any:
    """Floats become fixed 6-decimal strings, like the canonical hashing does."""
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, dict):
        return {k: _six(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_six(v) for v in value]
    return value


def check(name: str, data: dict[str, Any]) -> None:
    text = json.dumps(_six(data), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path = GOLDEN_DIR / f"{name}.json"
    if os.environ.get("TRACE_GOLDEN_BLESS") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    if not path.is_file():
        pytest.fail(f"golden {name} is missing: run `make golden-bless CONFIRM=1` and review it")
    expected = path.read_text(encoding="utf-8")
    assert text == expected, f"golden {name} changed: explain the diff, then bless"
