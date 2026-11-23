"""BuildService (A-08 minimal): one build in flight per case, idempotent by build_key, run in a
killable `multiprocessing` spawn child (`trace_worker.build_runner`).

This module never imports a decoder: the child imports pypdfium2 lazily on its own side.
On timeout the whole process tree is killed; stale builds are swept before each start.
TODO(M3/A-08): RLIMIT (needs the measured peak VM), SSE.
"""

from __future__ import annotations

import multiprocessing
import secrets
import threading
from datetime import UTC, datetime

from trace_adapters.clock import SystemClock
from trace_adapters.config_loader import load_config_bundle
from trace_adapters.sqlite.builds import BuildRepository
from trace_adapters.sqlite.store import SqliteClaimStore
from trace_api.settings import Settings
from trace_core.models.case import BuildStatus
from trace_core.normalise.time import fmt_utc
from trace_worker.build_runner import BuildPaths, run_build
from trace_worker.child_guard import kill_tree
from trace_worker.env import build_key
from trace_worker.sweep import sweep_stale

_OOM_EXIT_CODES = frozenset({-9, 137})


def _now() -> str:
    return fmt_utc(datetime.now(UTC))


class BuildService:
    def __init__(self, settings: Settings, repo: BuildRepository, store: SqliteClaimStore) -> None:
        self._settings = settings
        self._repo = repo
        self._store = store

    def start(self, case_id: str) -> BuildStatus:
        """Queue and spawn a build. Same inputs -> the existing build (idempotent).
        Raises LookupError for an unknown case, BuildInProgress for a concurrent build."""
        sweep_stale(self._repo, SystemClock())  # a build orphaned by a restart frees its slot
        manifest = self._store.load_manifest(case_id)
        if manifest is None:
            raise LookupError("unknown case")
        key = build_key(manifest, load_config_bundle())
        existing = self._repo.active_for_key(key)
        if existing is not None:
            return existing
        build_id = "bld_" + secrets.token_hex(8)
        self._repo.create(build_id, case_id, key, _now())
        paths = BuildPaths(
            db=str(self._settings.db_path),
            blobs=str(self._settings.blobs_dir),
            derived=str(self._settings.derived_dir),
            renders=str(self._settings.renders_dir),
        )
        process = multiprocessing.get_context("spawn").Process(
            target=run_build, args=(paths, case_id, build_id)
        )
        process.start()
        threading.Thread(
            target=self._watch, args=(process, build_id), daemon=True, name=f"watch-{build_id}"
        ).start()
        status = self._repo.get(build_id)
        assert status is not None  # noqa: S101
        return status

    def _watch(self, process: multiprocessing.process.BaseProcess, build_id: str) -> None:
        process.join(self._settings.build_timeout_s)
        if process.is_alive():
            kill_tree(process.pid or 0)  # the child AND its grandchildren (Tesseract)
            process.join(5)
            self._repo.finish_failed(build_id, "failed_timeout", "timeout", _now())
        elif process.exitcode != 0:
            status = "failed_resource" if process.exitcode in _OOM_EXIT_CODES else "failed"
            self._repo.finish_failed(build_id, status, f"exit_{process.exitcode}", _now())
