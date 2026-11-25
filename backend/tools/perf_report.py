"""`make check-perf` report (D-13, D-11): run the perf suite and write `data/perf_report.json` with
the reference machine's specs, so a number is never shown without the machine it came from.

    python -m tools.perf_report
"""

from __future__ import annotations

import json
import os
import platform
import subprocess  # noqa: S404 (fixed pytest invocation, no shell)
import sys
import tempfile
import xml.etree.ElementTree as ET  # noqa: S405 (our own junit file, not untrusted input)
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
OUT = REPO / "data" / "perf_report.json"
BUDGETS = {
    "test_build_under_budget": 60.0,
    "test_decision_rerun_p95_under_1500ms": 1.5,
    "test_proof_p95_under_1s_during_decision": 1.0,
    "test_decision_during_build_other_case_p95_under_2s": 2.0,
}


def reference_machine() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def parse_junit(path: Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for case in ET.parse(path).getroot().iter("testcase"):  # noqa: S314
        failed = case.find("failure") is not None or case.find("error") is not None
        out[case.get("name", "")] = {
            "seconds": float(case.get("time", "0")),
            "status": "failed" if failed else "passed",
        }
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "perf.xml"
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "tests/perf",
                "-m",
                "perf",
                f"--junitxml={xml}",
            ],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
        tests = parse_junit(xml) if xml.is_file() else {}
    report = {
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference_machine": reference_machine(),
        "budgets_s": BUDGETS,
        "tests": tests,
        "all_passed": proc.returncode == 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"out": str(OUT), "all_passed": proc.returncode == 0, "tests": len(tests)}))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
