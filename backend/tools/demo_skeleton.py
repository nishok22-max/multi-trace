"""demo-skeleton (M2): seed -> build the case -> print version + manifest_hash -> serve.

    uv run python -m tools.task demo-skeleton

Seeds `data/skeleton` (idempotent), builds the case in a spawn child (a second run finds the
same build and prints the same manifest hash), then serves the app on 127.0.0.1:8000 with
TRACE_DEV_AUTH=1 so the local viewer principal works. That flag is set HERE for this demo only;
the server default stays OFF (401).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "skeleton"
FRONTEND = REPO / "frontend"
HOST, PORT = "127.0.0.1", 8000


def _ensure_frontend() -> None:
    if (FRONTEND / "dist" / "case" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if npm is None or not (FRONTEND / "node_modules").is_dir():
        raise SystemExit(
            "frontend/dist is missing: run `npm ci --ignore-scripts` then `npm run build`"
        )
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)  # noqa: S603


def main() -> int:
    os.environ["TRACE_DATA_DIR"] = str(DATA_DIR)
    os.environ["TRACE_DEV_AUTH"] = "1"  # demo only; the default is off
    from tools.seed_build import seed_skeleton
    from trace_adapters.sqlite.builds import BuildRepository
    from trace_adapters.sqlite.store import SqliteClaimStore
    from trace_api.services.build_service import BuildService
    from trace_api.settings import load_settings

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_frontend()
    print("seeding ...", flush=True)
    case_id = seed_skeleton(DATA_DIR)
    settings = load_settings()
    store = SqliteClaimStore(settings.db_path)
    repo = BuildRepository(settings.db_path)
    status = BuildService(settings, repo, store).start(case_id)
    print(f"build {status.build_id}: {status.status}", flush=True)
    deadline = time.monotonic() + settings.build_timeout_s + 30
    while status.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.5)
        refreshed = repo.get(status.build_id)
        if refreshed is None:
            break
        status = refreshed
    if status.status != "done" or status.version is None:
        print(f"build did not finish: {status.status}", file=sys.stderr)
        return 1
    version = store.get_version(case_id, status.version)
    if version is None:
        return 1
    print(f"case          {case_id}", flush=True)
    print(f"version       {version.version}", flush=True)
    print(f"manifest_hash {version.manifest_hash}", flush=True)
    print(
        f"open          http://{HOST}:{PORT}/case?id={case_id}   (TRACE_DEV_AUTH=1, demo only)",
        flush=True,
    )
    import uvicorn

    uvicorn.run("trace_api.main:app", host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
