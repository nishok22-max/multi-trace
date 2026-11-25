"""The holdout tests (TEST_PLAN 7). EVERY test here is marked `holdout`: it is skipped by
`make test` and `make check`, and runs only under `make eval-holdout` (TRACE_HOLDOUT_RUN=1). Named:
test_quiet_day_false_alarm_rate_holdout, test_eval_report_has_pushed_config_commit,
test_holdout_report_required_fields, test_dev_holdout_machines_disjoint_real.

Nothing here tunes anything: if a number is bad, the number is what the holdout produced.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from trace_core.models.eval import EvalReport
from trace_eval.holdout import HOLDOUT_ENV
from trace_eval.holdout_run import (
    machine_split,
    manifest_for,
    plan,
    run_holdout,
)
from trace_eval.real_worlds import dataset_available
from trace_eval.report import load, required_problems

pytestmark = pytest.mark.holdout

REPO = Path(__file__).resolve().parents[3]
DATASET = REPO / "seed" / "dataset"
REPORT = REPO / "data" / "eval_report_holdout.json"
SEED_MANIFEST = REPO / "seed" / "faults" / "holdout" / "manifest.json"
HASHED = {
    "config_commit": "backend/config",
    "engine_commit": "backend/trace_core",
    "lockfile_commit": "backend/uv.lock",
}


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()


def git_info() -> dict[str, str]:
    info = {label: _git("log", "-1", "--format=%H", "--", path) for label, path in HASHED.items()}
    info["head"] = _git("rev-parse", "HEAD")
    info["remote_branch_of_head"] = (
        _git("branch", "-r", "--contains", info["head"]).splitlines() or [""]
    )[0].strip()
    return info


@pytest.fixture(scope="module")
def holdout_report() -> tuple[EvalReport, dict[str, object]]:
    """The one holdout run. Refuses to overwrite an existing report."""
    assert os.environ.get(HOLDOUT_ENV) == "1"
    if not dataset_available(DATASET):
        pytest.fail("the PdM dataset is not in seed/dataset; the holdout cannot run")
    if not REPORT.exists():
        run_holdout(REPORT, DATASET, git_info=git_info(), seed_manifest=SEED_MANIFEST)
    report, extras = load(REPORT)
    return report, extras


def test_dev_holdout_machines_disjoint_real() -> None:
    dev, holdout = machine_split(DATASET)
    assert not set(dev) & set(holdout) and len(dev) + len(holdout) == 100
    manifest = manifest_for(holdout, plan(holdout, 8))
    assert manifest["holdout_machines"] == sorted(holdout)
    assert len(manifest["cases"]) >= 40  # type: ignore[arg-type]  # one quiet control per machine


def test_quiet_day_false_alarm_rate_holdout(
    holdout_report: tuple[EvalReport, dict[str, object]],
) -> None:
    """At least 200 real holdout quiet days, leave-block-out, Wilson 95%. Fails only if the lower
    bound of the interval is above 5% (the product's claim is "at most 5%")."""
    report, _ = holdout_report
    far = report.quiet_day_false_alarm
    assert far.n >= 200, f"only {far.n} holdout quiet days were evaluated"
    shown = f"{far.point:.4f} (95% CI {far.lower:.4f} to {far.upper:.4f}, n={far.n})"
    assert far.lower <= 0.05, f"quiet-day false alarms {shown}"


def test_holdout_report_required_fields(
    holdout_report: tuple[EvalReport, dict[str, object]],
) -> None:
    report, extras = holdout_report
    assert report.split == "holdout"
    assert required_problems(report, extras) == []
    assert report.gaps_read_as_normal == 0 and report.averaged_outputs == 0
    protocol = extras["protocol"]
    assert protocol["holdout_machines"] == 40 and protocol["dev_machines"] == 60  # type: ignore[index]
    assert "external" in str(extras["disclosure"]).lower()


def test_eval_report_has_pushed_config_commit(
    holdout_report: tuple[EvalReport, dict[str, object]],
) -> None:
    """The config, engine and lockfile commits the report names are each contained in a remote
    branch, so nothing it depends on could have been changed after seeing the result."""
    _, extras = holdout_report
    git = extras["git"]
    assert isinstance(git, dict)
    for label in HASHED:
        commit = git[label]
        assert commit, label
        branches = _git("branch", "-r", "--contains", commit)
        assert branches, f"{label} {commit[:12]} is not on the remote"
    print(json.dumps({k: v for k, v in git.items()}, indent=2))
