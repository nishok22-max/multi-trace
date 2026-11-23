"""D-03: append-only triggers, derived status, build idempotency, PRAGMAs, migrations."""

from __future__ import annotations

import inspect
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.factories import (
    CASE_ID,
    decision_event,
    make_case,
    make_claim,
    make_decision,
    make_review_item,
    make_source,
    make_version,
    opened_event,
    sha,
)
from trace_adapters.config_loader import load_config_bundle
from trace_adapters.sqlite.migrate import MIGRATIONS_DIR, apply_migrations
from trace_adapters.sqlite.store import SqliteClaimStore, connect
from trace_core.canonical import record_hash
from trace_core.errors import IntegrityError
from trace_core.ids import comparison_id, conflict_id, envelope_id, review_event_id
from trace_core.models.case import VersionMembers, VersionRecords
from trace_core.models.claims import ClaimRecord
from trace_core.models.records import (
    ComparisonRecord,
    ConflictRecord,
    Envelope,
    EscalateChoice,
    ExplainChoice,
    ReadingChoice,
    ReviewEvent,
)
from trace_core.models.records import ConflictRecord as _Conflict  # noqa: F401  (clarity)

EVIDENCE_TABLES = [
    "cases",
    "sources",
    "claims",
    "comparisons",
    "conflicts",
    "envelopes",
    "review_items",
    "decisions",
    "review_events",
    "versions",
    "version_claims",
    "extraction_cache",
]
OPERATIONAL_TABLES = {
    "users",
    "sessions",
    "login_attempts",
    "builds",
    "eval_runs",
    "schema_migrations",
}


def _full_store(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A store with a row in every evidence table except extraction_cache (raw insert)."""
    store = SqliteClaimStore(tmp_path / "trace.db")
    claims = [make_claim(0), make_claim(1)]
    item = make_review_item([c.claim_id for c in claims])
    cmp_ = ComparisonRecord(
        comparison_id=comparison_id([c.claim_id for c in claims], sha("cfg")),
        claim_a=claims[0].claim_id,
        claim_b=claims[1].claim_id,
        config_hash=sha("cfg"),
        checks=[],
        outcome="cant_tell",
        reason="test",
    )
    conflict = ConflictRecord(
        conflict_id=conflict_id([c.claim_id for c in claims]),
        comparison_ids=[cmp_.comparison_id],
        sides=[c.claim_id for c in claims],
        magnitude={"statistic": "robust_max_z", "unit": "unitless"},
    )  # type: ignore[arg-type]
    params = load_config_bundle().envelope
    env = Envelope(
        envelope_id=envelope_id(
            "machine:21",
            "telemetry/machine:21",
            ["vibration"],
            "robust_max_z",
            "day",
            ["2015-01-01"],
            params,
            [],
            {},
        ),
        machine="machine:21",
        series_id="telemetry/machine:21",
        scope=["vibration"],
        quiet_days=[],
        n=0,
        med={},
        mad={},
        T_star=3.0,
        pooled="none",
        pool_members=[],
        degenerate_channels=[],
        params=params,
        partition_hashes={},
    )
    store.append(
        CASE_ID,
        [make_case(), make_source(), *claims, cmp_, conflict, env, item, opened_event(item)],
    )
    records = VersionRecords(
        claims=claims,
        comparisons=[cmp_],
        conflicts=[conflict],
        envelopes=[env],
        review_items=[item],
        decisions=[],
    )
    v1 = make_version(1, None, records)
    store.put_version(v1, VersionMembers.from_records(records))
    decision = make_decision(item)
    v2 = make_version(2, v1, records)
    store.commit_decision(CASE_ID, 1, decision, decision_event(decision, 1), v2)
    conn = connect(tmp_path / "trace.db")
    conn.execute(
        "INSERT INTO extraction_cache VALUES (?, 'pdfium.page_text', '1', ?, 'b', ?, ?)",
        (sha("in"), sha("p"), sha("art"), b"art"),
    )
    conn.close()
    return store, claims, item


@pytest.mark.parametrize("table", EVIDENCE_TABLES)
def test_trigger_aborts_update(tmp_path: Path, table: str) -> None:
    _full_store(tmp_path)
    conn = connect(tmp_path / "trace.db")
    try:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0  # noqa: S608
        column = {
            "version_claims": "record_id",
            "extraction_cache": "artifact_sha",
            "versions": "manifest_hash",
        }.get(table, "record_hash")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(f"UPDATE {table} SET {column} = 'x'")  # noqa: S608
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(f"DELETE FROM {table}")  # noqa: S608
    finally:
        conn.close()


def test_every_evidence_table_has_both_triggers_and_operational_ones_have_none(
    tmp_path: Path,
) -> None:
    SqliteClaimStore(tmp_path / "trace.db")
    conn = connect(tmp_path / "trace.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    conn.close()
    for table in tables - OPERATIONAL_TABLES - {"sqlite_sequence"}:
        assert {f"{table}_no_update", f"{table}_no_delete"} <= triggers, table
    for table in OPERATIONAL_TABLES - {"schema_migrations"}:
        assert not any(t.startswith(table) for t in triggers), table


def test_insert_or_replace_cannot_dodge_the_delete_trigger(tmp_path: Path) -> None:
    _, claims, _ = _full_store(tmp_path)
    conn = connect(tmp_path / "trace.db")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "INSERT OR REPLACE INTO claims (case_id, claim_id, attribute, claim_type, modality,"
            " record_hash, body) VALUES (?, ?, 'x', 'extracted', 'text', 'x', '{}')",
            (CASE_ID, claims[0].claim_id),
        )
    conn.close()


def test_no_update_paths_status_derived(tmp_path: Path) -> None:
    """N-1: no UPDATE/DELETE API, no stored status or version, and status comes from events."""
    banned = ("update", "delete", "remove", "set_status", "replace", "overwrite")
    public = [
        n
        for n, _ in inspect.getmembers(SqliteClaimStore, inspect.isfunction)
        if not n.startswith("_")
    ]
    assert not [n for n in public if any(b in n for b in banned)], public

    store, claims, item = _full_store(tmp_path)
    conn = connect(tmp_path / "trace.db")
    for table in EVIDENCE_TABLES:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608
        assert "status" not in cols, table
    assert "version" not in {r[1] for r in conn.execute("PRAGMA table_info(claims)")}
    assert "status" not in ClaimRecord.model_fields and "version" not in ClaimRecord.model_fields

    def status(rid: str) -> tuple[str, int]:
        row = conn.execute(
            "SELECT status, explained FROM review_status WHERE review_id = ?", (rid,)
        ).fetchone()
        return row[0], row[1]

    assert status(item.review_id) == ("decided", 0)  # _full_store decided it

    # a fresh item walks through open -> escalated -> decided -> stale -> open, status derived
    item2 = make_review_item([c.claim_id for c in claims], n=2)
    store.append(CASE_ID, [item2, opened_event(item2)])
    assert status(item2.review_id) == ("open", 0)
    latest = store.latest(CASE_ID)
    assert latest is not None
    esc = make_decision(item2, EscalateChoice(), base_version=2)
    v3 = make_version(3, latest, latest.records)
    store.commit_decision(CASE_ID, 2, esc, decision_event(esc, 1), v3)
    assert status(item2.review_id) == ("escalated", 0)
    res = make_decision(item2, ReadingChoice(verdict="accept"), base_version=3, sub="senior1")
    v4 = make_version(4, v3, v3.records)
    store.commit_decision(CASE_ID, 3, res, decision_event(res, 2), v4)
    assert status(item2.review_id) == ("decided", 0)
    stale = ReviewEvent(
        event_id=review_event_id(item2.review_id, "stale", 3),
        seq=3,
        review_id=item2.review_id,
        kind="stale",
        at="2015-03-15T09:10:00Z",
    )
    store.append(CASE_ID, [stale])
    assert status(item2.review_id) == ("stale", 0)
    reopened = ReviewEvent(
        event_id=review_event_id(item2.review_id, "opened", 4),
        seq=4,
        review_id=item2.review_id,
        kind="opened",
        at="2015-03-15T09:10:00Z",
    )
    store.append(CASE_ID, [reopened])
    assert status(item2.review_id) == ("open", 0)

    # a conflict_explain item: 'explained' is a flag, never a status; the conflict view follows it
    item3 = make_review_item([c.claim_id for c in claims], n=3, review_type="conflict_explain")
    store.append(CASE_ID, [item3, opened_event(item3)])
    assert conn.execute("SELECT status FROM conflict_status").fetchone()[0] == "open"
    ex = make_decision(item3, ExplainChoice(explanation="planned maintenance"), base_version=4)
    v5 = make_version(5, v4, v4.records)
    store.commit_decision(CASE_ID, 4, ex, decision_event(ex, 1), v5)
    assert status(item3.review_id) == ("open", 1)
    assert conn.execute("SELECT status FROM conflict_status").fetchone()[0] == "explained"
    conn.close()


def test_failed_build_same_key_can_retry(tmp_path: Path) -> None:
    SqliteClaimStore(tmp_path / "trace.db")
    conn = connect(tmp_path / "trace.db")
    conn.execute(
        "INSERT INTO cases VALUES (?, 't', '[]', 'a', 'b', 'UTC', 'c', 'h', '{}')", (CASE_ID,)
    )

    def add(build_id: str, key: str, status: str = "queued") -> None:
        conn.execute(
            "INSERT INTO builds (build_id, case_id, build_key, status) VALUES (?, ?, ?, ?)",
            (build_id, CASE_ID, key, status),
        )

    add("b1", "key-1")
    with pytest.raises(sqlite3.IntegrityError):  # same key while queued/running/done
        add("b2", "key-1")
    with pytest.raises(sqlite3.IntegrityError):  # second build in flight for the case
        add("b3", "key-2")
    conn.execute("UPDATE builds SET status = 'failed_timeout' WHERE build_id = 'b1'")  # mutable
    add("b4", "key-1")  # the failed build no longer blocks the same key
    conn.execute("UPDATE builds SET status = 'done', version = 1 WHERE build_id = 'b4'")
    with pytest.raises(sqlite3.IntegrityError):  # a done build keeps its key
        add("b5", "key-1")
    add("b6", "key-9")  # a new key can run once nothing is in flight
    conn.close()


def test_connection_pragmas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    assert one("PRAGMA journal_mode").lower() == "wal"
    assert one("PRAGMA synchronous") == 1  # NORMAL
    assert one("PRAGMA busy_timeout") == 5000
    assert one("PRAGMA foreign_keys") == 1
    assert one("PRAGMA mmap_size") == 64 * 1024 * 1024
    assert one("PRAGMA recursive_triggers") == 1
    assert conn.isolation_level is None
    conn.close()


def test_migrations_apply_once_and_detect_changes(tmp_path: Path) -> None:
    conn = connect(tmp_path / "m.db")
    assert apply_migrations(conn) == [
        "001_schema.sql",
        "002_append_only_triggers.sql",
        "003_indexes.sql",
        "004_status_views.sql",
        "005_eval_runs.sql",
    ]
    assert apply_migrations(conn) == []
    copy = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, copy)
    (copy / "003_indexes.sql").write_text("-- edited after it was applied\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        apply_migrations(conn, copy)
    conn.close()


def test_two_stores_racing_one_wins_one_is_moved(tmp_path: Path) -> None:
    store_a, claims, item = _full_store(tmp_path)
    store_b = SqliteClaimStore(tmp_path / "trace.db")
    latest = store_a.latest(CASE_ID)
    assert latest is not None
    item2 = make_review_item([c.claim_id for c in claims], n=5)
    store_a.append(CASE_ID, [item2, opened_event(item2)])
    d1 = make_decision(item2, base_version=2, sub="a")
    d2 = make_decision(item2, ReadingChoice(verdict="accept"), base_version=2, sub="b")
    from trace_core.ports import Committed, Moved

    first = store_a.commit_decision(
        CASE_ID, 2, d1, decision_event(d1, 1), make_version(3, latest, latest.records)
    )
    second = store_b.commit_decision(
        CASE_ID, 2, d2, decision_event(d2, 1), make_version(3, latest, latest.records)
    )
    assert isinstance(first, Committed) and second == Moved(latest=3)


def test_record_hash_of_rows_matches_models(tmp_path: Path) -> None:
    _, claims, item = _full_store(tmp_path)
    conn = connect(tmp_path / "trace.db")
    stored = conn.execute(
        "SELECT record_hash FROM review_items WHERE review_id = ?", (item.review_id,)
    ).fetchone()[0]
    assert stored == record_hash(item)
    assert (
        conn.execute(
            "SELECT record_hash FROM claims WHERE claim_id = ?", (claims[0].claim_id,)
        ).fetchone()[0]
        == claims[0].record_hash
    )
    conn.close()
