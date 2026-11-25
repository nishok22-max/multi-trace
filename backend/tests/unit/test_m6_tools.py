"""M6 tools: anchor, replay-verify, perf report, seed users, rehearsal, slide numbers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.skeleton.world import build_version, synthetic_world
from tools import anchor, perf_report, rehearse, replay_verify, seed_users, slide_numbers
from trace_api.services.anchors import anchored_roots, is_anchored

NOW = datetime(2015, 8, 6, 4, 0, tzinfo=UTC)
ROOT = "a" * 64


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m6-data")
    world = synthetic_world(root, spike=True)
    world.store.commit_build(build_version(world), world.manifest())
    return root


def test_anchor_appends_new_roots_and_never_rewrites(tmp_path: Path) -> None:
    path = tmp_path / "anchors" / "demo_roots.txt"
    added = anchor.append_roots(path, [("case-a", 1, ROOT)], NOW)
    assert added == [f"2015-08-06T04:00:00Z case-a v1 {ROOT}"]
    first = path.read_text(encoding="utf-8")
    assert first.startswith("# ") and first.endswith("\n")
    again = anchor.append_roots(path, [("case-a", 1, ROOT), ("case-a", 2, "b" * 64)], NOW)
    assert len(again) == 1 and again[0].endswith("b" * 64)  # only the new root is added
    assert path.read_text(encoding="utf-8").startswith(first)  # existing lines are untouched
    assert anchored_roots(path) == {ROOT, "b" * 64}
    assert is_anchored(path, ROOT) and not is_anchored(path, "c" * 64)
    assert not is_anchored(tmp_path / "missing.txt", ROOT)


def test_anchor_reads_the_latest_root_of_every_case(data_dir: Path) -> None:
    (db,) = anchor.databases(data_dir)
    roots = anchor.latest_roots(db)
    assert len(roots) == 1 and roots[0][1] == 1 and len(roots[0][2]) == 64


def test_replay_verify_matches_every_stored_version(data_dir: Path) -> None:
    results = replay_verify.verify_dir(data_dir)
    assert len(results) == 1
    case, version, stored, rebuilt = results[0]
    assert (
        version == 1 and stored == rebuilt
    )  # the manifest does not depend on the machine or clock


def test_replay_verify_fails_when_a_stored_byte_changed(tmp_path: Path) -> None:
    world = synthetic_world(tmp_path, spike=True)
    world.store.commit_build(build_version(world), world.manifest())
    text = next(s for s in world.manifest().sources if s.modality == "text")
    blob = tmp_path / "blobs" / text.sha256[:2] / text.sha256
    blob.write_bytes(blob.read_bytes() + b"x")
    with pytest.raises(Exception):  # noqa: B017, PT011 (the rebuild cannot even read the source)
        replay_verify.verify_dir(tmp_path)


def test_perf_report_parses_junit_and_names_the_machine(tmp_path: Path) -> None:
    xml = tmp_path / "p.xml"
    xml.write_text(
        '<testsuites><testsuite><testcase name="test_a" time="1.5"/>'
        '<testcase name="test_b" time="0.2"><failure message="x"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    parsed = perf_report.parse_junit(xml)
    assert parsed["test_a"] == {"seconds": 1.5, "status": "passed"}
    assert parsed["test_b"]["status"] == "failed"
    machine = perf_report.reference_machine()
    assert {"platform", "cpu_count", "python"} <= set(machine)
    assert "test_build_under_budget" in perf_report.BUDGETS


def test_seed_users_never_prints_or_stores_passwords_in_the_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    creds = tmp_path / "credentials.local.txt"
    created = seed_users.seed_users(tmp_path / "data", creds)
    assert created == [name for name, _ in seed_users.PERSONAS] and "judge" in created
    rows = [line.split("\t") for line in creds.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(created) and all(len(r) == 3 and len(r[2]) >= 16 for r in rows)
    assert len({r[2] for r in rows}) == len(rows)  # a password per persona, all different
    out = capsys.readouterr().out
    assert all(r[2] not in out for r in rows)
    # idempotent: a second run creates nobody and leaves the file alone
    before = creds.read_text(encoding="utf-8")
    assert seed_users.seed_users(tmp_path / "data", creds) == []
    assert creds.read_text(encoding="utf-8") == before
    # the stored form is an argon2 hash, never the password
    import sqlite3

    stored = (
        sqlite3.connect(tmp_path / "data" / "trace.db")
        .execute("SELECT password_hash FROM users WHERE username='judge'")
        .fetchone()[0]
    )
    assert stored.startswith("$argon2id$") and rows[-1][2] not in stored


def test_rehearsal_lists_what_a_machine_cannot_check() -> None:
    items = rehearse.run(full=False)
    by_text = {i.text: i for i in items}
    manual = [i for i in items if i.status == "MANUAL"]
    assert len(manual) == 3 and any("backup video" in i.text for i in manual)
    assert by_text["goldens for Demos 0-6 green"].status == "not run"  # never claimed unrun
    text = rehearse.render(items)
    assert "HARDENING section 6" in text and "Open items" in text


def test_rehearsal_holdout_item_is_pending_until_a_holdout_report_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rehearse, "REPO", tmp_path)
    assert rehearse.check_holdout_report().status == "PENDING"
    assert rehearse.check_anchors().status == "PENDING"
    assert rehearse.check_judge_card().status == "PENDING"


def test_slide_numbers_are_read_from_engine_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    section = "\n".join(slide_numbers.demo0_section())
    golden = json.loads((slide_numbers.GOLDEN / "demo0_headline.json").read_text(encoding="utf-8"))
    assert golden["state"]["T_D"] in section and golden["state"]["T_star"] in section
    missing = slide_numbers.eval_section("Holdout evaluation", tmp_path / "nope.json")
    assert "Not run yet" in "\n".join(missing)  # an unrun evaluation is never invented
