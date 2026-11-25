"""M5 evaluation tests (TEST_PLAN §7). Named: test_ece_known_fixture, test_brier_known_values,
test_bootstrap_ci_seeded_and_covers_point, test_baseline_output_generated,
test_eval_report_required_fields, test_quiet_day_false_alarm_rate_dev,
test_dev_suite_never_reads_holdout, test_holdout_marker_excluded_from_test_and_check,
test_holdout_requires_clean_tree, test_eval_report_has_pushed_config_commit (precondition logic),
test_report_superseded_on_engine_change, test_label_kit_roundtrip, plus the engine results."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from trace_core.models.eval import EvalReport
from trace_eval import holdout, label_kit
from trace_eval.baselines import BaselineInput, fusion, tfidf
from trace_eval.metrics import (
    bootstrap_ci,
    brier,
    calibration_bins,
    ece,
    wilson_ci,
)
from trace_eval.report import load, required_problems, superseded
from trace_eval.runner import DEV_MACHINES, run_dev

BACKEND = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------------- metrics
def test_wilson_ci_matches_the_documented_values() -> None:
    lo, hi = wilson_ci(0, 200)
    assert (round(lo, 4), round(hi, 4)) == (0.0, 0.0188)
    lo, hi = wilson_ci(10, 200)
    # TEST_PLAN 7 quotes 0.0899; the standard Wilson upper bound (z = 1.95996) is 0.0896
    assert round(lo, 4) == 0.0274 and abs(hi - 0.0899) < 5e-4
    lo, hi = wilson_ci(5, 100)
    assert (round(lo, 4), round(hi, 4)) == (0.0215, 0.1118)


def test_ece_known_fixture() -> None:
    # bin [0.9, 1.0]: 4 items, confidence 0.95, 3 right (accuracy 0.75) -> |0.75 - 0.95| = 0.2
    # bin [0.5, 0.6): 2 items, confidence 0.55, 1 right (0.5)            -> |0.5 - 0.55|  = 0.05
    conf = [0.95, 0.95, 0.95, 0.95, 0.55, 0.55]
    right = [True, True, True, False, True, False]
    expected = 4 / 6 * 0.2 + 2 / 6 * 0.05
    assert ece(conf, right) == pytest.approx(expected)
    bins = calibration_bins(conf, right)
    assert [b.n for b in bins] == [0, 0, 0, 0, 0, 2, 0, 0, 0, 4]  # empty bins reported, not filled
    assert bins[0].accuracy is None and bins[9].accuracy == 0.75
    assert ece([], []) == 0.0
    assert ece([1.0, 1.0], [True, True]) == 0.0  # a perfectly calibrated extreme
    with pytest.raises(ValueError):
        calibration_bins([1.2], [True])


def test_brier_known_values() -> None:
    assert brier([1.0, 0.0, 0.5], [True, False, True]) == pytest.approx(0.25 / 3)
    assert brier([0.5, 0.5], [True, False]) == pytest.approx(0.25)
    assert brier([1.0], [False]) == 1.0
    assert brier([], []) == 0.0


def test_bootstrap_ci_seeded_and_covers_point() -> None:
    conf = [0.9, 0.8, 0.7, 0.95, 0.6, 0.85, 0.75, 0.65, 0.99, 0.55] * 4
    right = [True, True, False, True, False, True, True, False, True, False] * 4

    def stat(idx: object) -> float:
        picks = list(idx)  # type: ignore[call-overload]
        return ece([conf[i] for i in picks], [right[i] for i in picks])

    one = bootstrap_ci(stat, len(conf), resamples=1000, seed=3)
    two = bootstrap_ci(stat, len(conf), resamples=1000, seed=3)
    assert one == two  # reproducible
    assert bootstrap_ci(stat, len(conf), resamples=1000, seed=4) != one
    point = ece(conf, right)
    assert one[0] <= point <= one[1]
    assert bootstrap_ci(stat, 0) == (0.0, 1.0)


# --------------------------------------------------------------------------- the dev run
@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[EvalReport, dict[str, object], Path]:
    out = tmp_path_factory.mktemp("eval") / "report.json"
    run_dev(out, n_per_kind=2, seed=7)
    report, extras = load(out)
    return report, extras, out


def test_eval_report_required_fields(run: tuple[EvalReport, dict[str, object], Path]) -> None:
    report, extras, _ = run
    assert required_problems(report, extras) == []
    assert report.split == "dev" and set(report.per_fault) == {
        "contradicting_note",
        "late_timestamp",
        "removed_source",
        "flatline",
        "quiet_control",
    }
    assert all(p.n > 0 for p in report.per_fault.values())
    assert sum(b.n for b in report.bins) == sum(report.per_fault[k].n for k in report.per_fault)
    assert report.ece_after is None and report.brier_after is None  # no calibration fit yet
    assert extras["external_fault_share"] == 0.0 and "planted" in str(extras["disclosure"]).lower()
    lo, hi = extras["ece_ci"]  # type: ignore[misc]
    assert lo <= report.ece_before <= hi  # type: ignore[operator]
    broken = report.model_copy(update={"baselines": []})
    assert "baseline outputs are missing" in required_problems(broken, extras)


def test_engine_results_on_the_planted_faults(
    run: tuple[EvalReport, dict[str, object], Path],
) -> None:
    report, extras, _ = run
    assert report.gaps_read_as_normal == 0  # no data is never normal
    assert report.averaged_outputs == 0  # a conflict is never averaged
    assert report.overall.recall == 1.0 and report.overall.precision == 1.0
    assert report.provenance_reresolve_rate == 1.0
    assert extras["outcomes"]["contradicting_note"] == {"disagree": 2}  # type: ignore[index]
    assert extras["outcomes"]["removed_source"] == {"cant_tell": 2}  # type: ignore[index]
    assert report.false_conflict_rate.point == 0.0  # the gate raised no false conflicts
    assert (
        report.entity_accuracy_at1 >= 0.9
        and report.entity_accuracy_at3 >= report.entity_accuracy_at1
    )


def test_quiet_day_false_alarm_rate_dev(run: tuple[EvalReport, dict[str, object], Path]) -> None:
    """Fails only if the Wilson lower bound is above 5%: the point estimate is reported."""
    far = run[0].quiet_day_false_alarm
    assert far.n > 0 and far.lower <= 0.05, f"false alarms {far.point:.3f} (CI {far.lower:.3f})"


def test_baseline_output_generated(run: tuple[EvalReport, dict[str, object], Path]) -> None:
    report, extras, _ = run
    by_name = {b.name: b for b in report.baselines}
    assert set(by_name) == {"tfidf", "fusion", "nogate"}
    assert by_name["tfidf"].answer_text.startswith("[note]")
    assert "last write wins" in by_name["fusion"].answer_text
    gate, nogate = extras["false_conflicts"]["gate"], extras["false_conflicts"]["nogate"]  # type: ignore[index]
    assert gate[1] == nogate[1] and nogate[0] > gate[0]  # same pairs: the gate prevents conflicts
    assert extras["baseline_surfaced_planted_conflict"]["planted_cases"] == 4  # type: ignore[index]
    # the outputs are computed: change the data and the text changes
    base = dict(
        machine="machine 1", day="2015-06-23", note_sentences=["machine 1 ran normally."],
        note_written_at="t", history={"v": [1.0, 2.0, 3.0, 2.0]},
    )  # fmt: skip
    a = fusion.answer(BaselineInput(readings={"v": [2.0, 2.0]}, **base))  # type: ignore[arg-type]
    b = fusion.answer(BaselineInput(readings={"v": [9.0, 9.0]}, **base))  # type: ignore[arg-type]
    assert a.answer_text != b.answer_text and not a.surfaced_conflict and b.surfaced_conflict
    t = tfidf.answer(BaselineInput(readings={"v": [2.0]}, **base))  # type: ignore[arg-type]
    assert t.score is not None and 0.0 <= t.score <= 1.0 and not t.provenance_correct


def test_the_dev_runner_refuses_non_dev_machines(tmp_path: Path) -> None:
    assert DEV_MACHINES[0] == 101
    with pytest.raises(ValueError):
        run_dev(tmp_path / "r.json", machines=[999])


def test_report_superseded_on_engine_change(
    run: tuple[EvalReport, dict[str, object], Path],
) -> None:
    report = run[0]
    assert not superseded(report, report.engine_sha)
    assert superseded(report, "f" * 64)


# --------------------------------------------------------------------------- holdout hygiene
def test_dev_suite_never_reads_holdout(tmp_path: Path) -> None:
    secret = tmp_path / "seed" / "faults" / "holdout" / "faults.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("{}", encoding="utf-8")
    with pytest.raises(PermissionError):
        secret.open("r")  # the audit hook (conftest) stops an unmarked test


@pytest.mark.holdout
def test_holdout_data_is_readable_only_in_a_holdout_run(tmp_path: Path) -> None:
    secret = tmp_path / "faults" / "holdout" / "x.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("{}", encoding="utf-8")
    assert secret.read_text(encoding="utf-8") == "{}"  # never executed outside `make eval-holdout`


def test_holdout_marker_excluded_from_test_and_check() -> None:
    env = {**os.environ}
    env.pop(holdout.HOLDOUT_ENV, None)
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "holdout", "tests/eval"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    ).stdout
    assert "test_holdout_data_is_readable_only_in_a_holdout_run" in out  # it exists...
    run = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-q", "-m", "holdout", "tests/eval"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    ).stdout
    assert "skipped" in run and "passed" not in run  # ...and is skipped without the env flag
    task = (BACKEND / "tools" / "task.py").read_text(encoding="utf-8")
    assert "not holdout" in task  # make test / make check deselect it as well


def test_holdout_requires_clean_tree() -> None:
    def git(dirty: bool, pushed: bool):  # type: ignore[no-untyped-def]
        def run(args: list[str]) -> str:
            if args[0] == "status":
                return " M file.py\n" if dirty else ""
            return "  origin/main\n" if pushed else ""

        return run

    inputs = {"config": "c1", "engine": "e1", "lockfile": "l1"}
    assert holdout.allowed(holdout.check_holdout(git(False, True), inputs))
    dirty = holdout.check_holdout(git(True, True), inputs)
    assert not holdout.allowed(dirty) and "uncommitted" in dirty[0].detail
    unpushed = holdout.check_holdout(git(False, False), inputs)
    assert not holdout.allowed(unpushed)
    assert [p.name for p in unpushed if not p.ok] == [
        "config on the remote",
        "engine on the remote",
        "lockfile on the remote",
    ]


def test_eval_report_has_pushed_config_commit_logic() -> None:
    """Each of the three hashes is checked separately against `git branch -r --contains`."""
    seen: list[list[str]] = []

    def git(args: list[str]) -> str:
        seen.append(args)
        return "  origin/main\n"

    pre = holdout.hash_is_pushed(git, "engine", "abc123")
    assert pre.ok and seen == [["branch", "-r", "--contains", "abc123"]]


# ------------------------------------------------------------------------------ label kit
def test_label_kit_roundtrip() -> None:
    rows = [
        label_kit.LabelRow(
            "clm_1", "Machine 21 ran normally", entity="machine:21", outcome="disagree"
        ),
        label_kit.LabelRow("clm_2", "Pressure 6.9 bar", value="6.9", unit="bar", time="2015-08-05"),
    ]
    text = label_kit.export_yaml(rows, labeller="dana")
    labeller, back = label_kit.import_yaml(text)
    assert labeller == "dana" and back == rows  # every PRD 12.1 field survives
    with pytest.raises(ValueError):
        label_kit.import_yaml(label_kit.export_yaml(rows, labeller=""))  # the labeller is recorded
    with pytest.raises(ValueError):
        label_kit.import_yaml(text.replace("disagree", "maybe"))


def test_the_report_file_is_valid_json_for_the_api(
    run: tuple[EvalReport, dict[str, object], Path],
) -> None:
    path = run[2]
    assert EvalReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
