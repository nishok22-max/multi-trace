"""Evaluation runs (D-08, T-34): one in flight (the database enforces it), run in a killable
spawned child (it builds cases with the real engine and decodes nothing untrusted), report written
to `data/eval_report.json` only when the child succeeds. The API never runs the holdout: this
service starts the DEV run only."""

from __future__ import annotations

import multiprocessing
import secrets
import threading
from datetime import UTC, datetime

from trace_adapters.sqlite.eval_runs import EvalRunRepository
from trace_api.settings import Settings
from trace_core.normalise.time import fmt_utc
from trace_worker.child_guard import kill_tree

DEV_CASES_PER_KIND = 3
EVAL_TIMEOUT_SECONDS = 900


def _now() -> str:
    return fmt_utc(datetime.now(UTC))


def eval_child(out: str, n_per_kind: int, seed: int) -> None:
    """Spawn target: runs the dev evaluation and writes the report atomically."""
    import os
    from pathlib import Path

    from trace_eval.runner import run_dev

    tmp = Path(out).with_name(Path(out).name + ".partial")
    run_dev(tmp, n_per_kind=n_per_kind, seed=seed)
    sidecar = tmp.with_name(tmp.name + ".extras.json")
    os.replace(sidecar, Path(out).with_name(Path(out).name + ".extras.json"))
    os.replace(tmp, out)  # the report appears only when it is complete


class EvalService:
    def __init__(self, settings: Settings, repo: EvalRunRepository) -> None:
        self._settings = settings
        self._repo = repo

    @property
    def report_path(self) -> str:
        return str(self._settings.data_dir / "eval_report.json")

    def start(self, seed: int = 7) -> str:
        """Returns the run id. Raises `EvalInProgress` when a run is already running."""
        run_id = "evr_" + secrets.token_hex(8)
        self._repo.start(run_id, _now())  # the unique index is the single-flight lock
        process = multiprocessing.get_context("spawn").Process(
            target=eval_child, args=(self.report_path, DEV_CASES_PER_KIND, seed)
        )
        process.start()
        threading.Thread(
            target=self._watch, args=(process, run_id), daemon=True, name=f"watch-{run_id}"
        ).start()
        return run_id

    def _watch(self, process: multiprocessing.process.BaseProcess, run_id: str) -> None:
        process.join(EVAL_TIMEOUT_SECONDS)
        if process.is_alive():
            kill_tree(process.pid or 0)
            process.join(5)
            self._repo.finish(run_id, "failed_timeout", _now(), "timeout")
        elif process.exitcode == 0:
            self._repo.finish(run_id, "done", _now())
        else:
            self._repo.finish(run_id, "failed", _now(), f"exit_{process.exitcode}")
