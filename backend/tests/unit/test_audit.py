"""`make audit` and the holdout task (M5, D-09/D-11): the audit blocks on unwaived critical or high
findings and never reports an unrun scan as passed; the holdout task refuses a dirty tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import audit, task


def test_secret_scan_finds_keys_and_skips_tests_and_docs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text('KEY = "gsk_' + "a" * 24 + '"\n', encoding="utf-8")
    (tmp_path / "src" / "ok.py").write_text('KEY = os.environ["GROQ_API_KEY"]\n', encoding="utf-8")
    (tmp_path / "src" / "k.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n", encoding="utf-8")
    sentinel = tmp_path / "backend" / "tests"
    sentinel.mkdir(parents=True)
    (sentinel / "t.py").write_text('S = "gsk_' + "b" * 24 + '"\n', encoding="utf-8")
    files = ["src/a.py", "src/ok.py", "src/k.pem", "backend/tests/t.py"]
    hits = audit.scan_secrets(files, root=tmp_path)
    assert sorted(hits) == ["src/a.py: Groq-style key", "src/k.pem: private key block"]


def test_the_repository_itself_has_no_tracked_secrets() -> None:
    check = audit.check_secrets()
    assert check.status == "passed", check.items


def test_waivers_are_read_from_the_waivers_section_only() -> None:
    notes = (
        "## Audit\n- not a waiver: x\n## Waivers\n- npm audit (frontend): dev-only, no fix yet\n"
    )
    assert audit.waived(notes) == {"npm audit (frontend)"}


def test_only_unwaived_critical_or_high_failures_block() -> None:
    checks = [
        audit.Check("a", "failed", "x", severity="high"),
        audit.Check("b", "failed", "x", severity="critical"),
        audit.Check("c", "failed", "x", severity="medium"),
        audit.Check("d", "skipped", "offline", severity="high"),
        audit.Check("e", "passed", "ok", severity="critical"),
    ]
    assert [c.name for c in audit.evaluate(checks)] == ["a", "b"]
    waiver = "## Waivers\n- a: accepted until the next dependency bump\n"
    assert [c.name for c in audit.evaluate(checks, waiver)] == ["b"]


def test_online_scans_are_skipped_not_passed_when_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACE_AUDIT_ONLINE", raising=False)
    check = audit.check_online("npm audit", ["npm", "audit"], Path("."), r"high")
    assert check.status == "skipped" and "TRACE_AUDIT_ONLINE" in check.detail


def test_the_notes_render_the_hashes_results_and_waivers() -> None:
    info = {
        "commit": "c" * 40,
        "tree": "clean",
        "config_hash": "1" * 64,
        "engine_sha": "2" * 64,
        "lockfile_hash": "3" * 64,
    }
    checks = [
        audit.Check("secrets", "passed", "ok"),
        audit.Check("npm audit", "skipped", "offline"),
    ]
    text = audit.render(checks, info, [], "- none: no finding is waived.")
    assert "config_hash" in text and "1" * 64 in text and "| npm audit | SKIPPED |" in text
    assert "## Waivers" in text and "no unwaived critical or high finding" in text


def test_the_holdout_task_refuses_a_dirty_tree(monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from trace_eval import holdout

    def fake_git(args: list[str], cwd: Path | None = None) -> str:
        if args[0] == "status":
            return " M backend/trace_core/x.py\n"
        if args[0] == "log":
            return "abc123\n"
        return "  origin/main\n"

    monkeypatch.setattr(holdout, "run_git", fake_git)
    assert task.eval_holdout() == 2  # refused; no test ran
    assert "uncommitted changes" in capsys.readouterr().out
