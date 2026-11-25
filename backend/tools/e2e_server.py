"""Seeded server for the Playwright specs (C-12). Builds four cases of synthetic data in a fresh
data directory, creates test users, and serves the real app (built frontend + API, enforcing CSP)
on 127.0.0.1. Test credentials exist only for this local, throwaway database.

    python -m tools.e2e_server            # port 8765, data in a new temp directory

Cases (each with a real build, so every number is computed by the engine):
  case-main    read-only specs: a disagreement (planted vibration spike) and an ambiguous mention
  case-decide-1..3  the decision spec mutates one each (reviewer decision -> version 2)
  case-flip    its report is unique, so the byte-flip spec can corrupt its blob alone
  case-xss     its report quotes an HTML payload, which must only ever render as text
`e2e_info.json` in the data directory tells the specs where things are.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

import uvicorn
from reportlab.pdfgen.canvas import Canvas

PORT = int(os.environ.get("TRACE_E2E_PORT", "8765"))
PASSWORD = "e2e-test-password-123"  # noqa: S105 (local throwaway database only)
PAYLOAD = "<img src=x onerror=alert(1)>"

BASE_LINES = [
    "Shift report (synthetic document written for the e2e tests)",
    "Report date: 06 Aug 2015 09:10",
    "Reporting period: 05 Aug 2015",
    "Machine 21 ran normally through both shifts.",
    "Press 21 ran normally on the second shift.",
]


def report(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(595.2756, 841.8898), pageCompression=0, invariant=1)
    canvas.setFont("Helvetica", 12)
    y = 780.0
    for line in lines:
        canvas.drawString(72, y, line)
        y -= 24
    canvas.save()
    return buf.getvalue()


def build_all(data_dir: Path) -> dict[str, object]:
    # Imported here: the data directory must be configured before the app modules read it.
    from tests.skeleton.world import build_version, synthetic_world
    from trace_adapters.clock import SystemClock
    from trace_adapters.sqlite.store import SqliteClaimStore
    from trace_api.security.sessions import AuthRepository
    from trace_worker.prerender import prerender

    flip = [*BASE_LINES[:3], "Machine 21 ran normally on the flip case day.", BASE_LINES[4]]
    xss = [*BASE_LINES[:3], f"Machine 21 ran normally through both shifts {PAYLOAD}", BASE_LINES[4]]
    cases = {
        "case-main": report(BASE_LINES),
        # a review item is keyed by (document, locator), so each decision case needs its own
        # document: two cases sharing one blob would share one review item
        **{f"case-decide-{n}": report([*BASE_LINES, f"Log note {n}."]) for n in (1, 2, 3)},
        "case-flip": report(flip),
        "case-xss": report(xss),
    }
    info: dict[str, object] = {"data_dir": str(data_dir), "password": PASSWORD, "cases": {}}
    for case_id, pdf in cases.items():
        world = synthetic_world(data_dir, case_id=case_id, report=pdf, spike=True)
        version = build_version(world)
        world.store.commit_build(version, world.manifest())
        prerender(version, world.ports().blobs, data_dir / "renders")
        text = next(c for c in version.records.claims if c.modality == "text")
        info["cases"][case_id] = {  # type: ignore[index]
            "report_sha": text.evidence.sha256,  # type: ignore[union-attr]
            "manifest_hash": version.manifest_hash,
        }
    store = SqliteClaimStore(data_dir / "trace.db")
    repo = AuthRepository(store._path, SystemClock())  # noqa: SLF001 (same file, own connections)
    for user, role in (
        ("rita", "reviewer"),
        ("sam", "senior_reviewer"),
        ("ina", "ingestor"),
        ("eve", "evaluator"),
        ("vik", "viewer"),
    ):
        repo.create_user(f"u-{user}", user, user.title(), role, PASSWORD)  # type: ignore[arg-type]
    # a real dev evaluation (engine-computed, seeded) so the evaluation page has a report to show
    from trace_eval.runner import run_dev

    run_dev(data_dir / "eval_report.json", n_per_kind=1, seed=7)
    (data_dir / "e2e_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main() -> int:
    data_dir = Path(os.environ.get("TRACE_E2E_DATA") or tempfile.mkdtemp(prefix="trace-e2e-"))
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TRACE_DATA_DIR"] = str(data_dir)
    os.environ["TRACE_ANCHORS"] = str(data_dir / "anchors.txt")  # a throwaway anchor file
    os.environ.pop("TRACE_DEV_AUTH", None)  # real sessions: the specs log in
    info = build_all(data_dir)
    main_root = info["cases"]["case-main"]["manifest_hash"]  # type: ignore[index]
    (data_dir / "anchors.txt").write_text(
        f"# e2e anchors\n2015-08-06T04:00:00Z case-main v1 {main_root}\n", encoding="utf-8"
    )
    from trace_api.main import app

    print(f"e2e server ready on http://127.0.0.1:{PORT} (data {data_dir})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
