"""Native smoke check (`smoke-native`). Writes data/smoke_report.json.

Reports exactly which human install step is missing. Makes no network calls.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def is_local_disk(path: Path) -> tuple[bool, str]:
    """Reject network shares and WSL paths for the data dir (SQLite must be on a local disk)."""
    raw = str(path)
    low = raw.lower().replace("/", "\\")
    if low.startswith("\\\\"):
        return False, f"{raw} is a network/UNC or WSL path"
    if "wsl" in low.split("\\")[2:3] or low.startswith("\\wsl"):
        return False, f"{raw} is a WSL path"
    if sys.platform == "win32":
        import ctypes

        drive = os.path.splitdrive(os.path.abspath(raw))[0]
        if drive:
            kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")  # type: ignore[attr-defined]
            if kind == 4:  # DRIVE_REMOTE
                return False, f"{drive} is a network drive"
    return True, f"{raw} is local"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, type(exc).__name__
    return p.returncode, (p.stdout + p.stderr).strip()


def check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) == (3, 11)
    return ok, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if ok else " (need 3.11)")


def check_uv() -> tuple[bool, str]:
    path = shutil.which("uv")
    if path:
        return True, _run([path, "--version"])[1]
    # Accept a pip-installed uv (`python -m uv`) when the uv script is not on PATH.
    code, out = _run([sys.executable, "-m", "uv", "--version"])
    if code == 0:
        return True, f"{out} (via python -m uv, not on PATH)"
    code, out = _run(["py", "-3.12", "-m", "uv", "--version"])
    if code == 0:
        return True, f"{out} (via py -3.12 -m uv, not on PATH)"
    return False, "uv not found (winget install astral-sh.uv)"


def check_node() -> tuple[bool, str]:
    path = shutil.which("node")
    if not path:
        return False, "node not found (install Node 20)"
    out = _run([path, "--version"])[1]
    m = re.match(r"v(\d+)\.", out)
    ok = m is not None and int(m.group(1)) >= 20
    return ok, out + ("" if ok else " (need Node 20 or newer)")


def check_tesseract() -> tuple[bool, str]:
    cmd = os.environ.get("TRACE_TESSERACT_CMD", "")
    if not cmd:
        return (
            False,
            "TRACE_TESSERACT_CMD is not set (install Tesseract 5, set it to tesseract.exe)",
        )
    code, out = _run([cmd, "--version"])
    first = out.splitlines()[0] if out else ""
    ok = code == 0 and re.match(r"tesseract v?5\.", first.lower()) is not None
    return ok, first or f"could not run {cmd}"


def check_tzdata() -> tuple[bool, str]:
    env = {**os.environ, "PYTHONTZPATH": ""}
    code, out = _run(
        [
            sys.executable,
            "-c",
            "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Berlin'); print('ok')",
        ],
        env,
    )
    return code == 0 and out.endswith(
        "ok"
    ), "tzdata works with PYTHONTZPATH empty" if code == 0 else out


def check_longpaths() -> tuple[bool, str]:
    git = shutil.which("git")
    if not git:
        return False, "git not found"
    _, out = _run([git, "config", "core.longpaths"])
    return out == "true", f"core.longpaths={out or 'unset'} (git config core.longpaths true)"


def check_data_dir() -> tuple[bool, str]:
    raw = os.environ.get("TRACE_DATA_DIR", "./data")
    path = Path(raw)
    if not path.is_absolute():
        path = REPO / path
    return is_local_disk(path)


def check_pdfium() -> tuple[bool, str]:
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument.new()
        doc.new_page(72, 72)
        buf = io.BytesIO()
        doc.save(buf)
        page = pdfium.PdfDocument(buf.getvalue())[0]
        bitmap = page.render(scale=1)
        ok = bitmap.width > 0 and bitmap.height > 0
        return (
            ok,
            f"pypdfium2 {pdfium.version.PYPDFIUM_INFO} rendered {bitmap.width}x{bitmap.height}",
        )
    except Exception as exc:  # noqa: BLE001 - report, never crash the smoke run
        return False, f"pypdfium2 failed: {type(exc).__name__}"


CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {
    "python_3_11": check_python,
    "uv": check_uv,
    "node_20": check_node,
    "tesseract_5": check_tesseract,
    "tzdata_empty_pythontzpath": check_tzdata,
    "git_core_longpaths": check_longpaths,
    "data_dir_local_disk": check_data_dir,
    "pypdfium2_render": check_pdfium,
}


def main() -> int:
    results: dict[str, dict[str, object]] = {}
    for name, fn in CHECKS.items():
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"check crashed: {type(exc).__name__}"
        results[name] = {"ok": ok, "detail": detail}
        print(f"[{'ok' if ok else 'FAIL'}] {name}: {detail}")
    data_dir = REPO / "data"
    data_dir.mkdir(exist_ok=True)
    report = {"passed": all(bool(r["ok"]) for r in results.values()), "checks": results}
    (data_dir / "smoke_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    missing = [n for n, r in results.items() if not r["ok"]]
    print(
        "smoke-native: PASS"
        if not missing
        else f"smoke-native: FAIL, missing: {', '.join(missing)}"
    )
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
