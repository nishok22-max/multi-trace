"""Properties and named tests of B-04/A-05: missing data never moves toward "agree".
Named: test_spike_in_gap_never_agree, prop_deleting_readings_never_toward_agree,
test_cell_pointer_row_sha_and_offset, test_envelope_refuses_without_log_coverage."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.factories import make_source, sha
from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_envelope_pooling import CASE, CFG, _write
from trace_adapters.telemetry_parquet import ParquetTelemetryReader
from trace_core.errors import LogCoverageError
from trace_core.models.evidence import TableCellPointer
from trace_core.models.records import CoveragePeriod
from trace_core.normalise.envelopes import learn_envelopes
from trace_core.read.table import read_table

LOG = (
    b'"datetime","machineID","errorID"\r\n'
    b'2015-07-10 07:00:00,21,"error1"\r\n'
    b'2015-07-11 09:30:00,22,"error3"\n'
)


def _outcome(version) -> str:  # type: ignore[no-untyped-def]
    # no comparison at all (every reading gone: only a gap claim remains) is not an agreement
    comparisons = version.records.comparisons
    return comparisons[0].outcome if comparisons else "none"


def test_spike_in_gap_never_agree(tmp_path: Path) -> None:
    """The spike hour (06) is missing: the violation is unobserved, so the ∀ claim must not agree.
    Disagreeing on a missing spike would be inventing data, so it can't tell."""
    version = build_version(synthetic_world(tmp_path, spike=True, drop_hours=(6,)))
    assert _outcome(version) == "cant_tell"
    assert "missing" in version.records.comparisons[0].reason


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    return synthetic_world(tmp_path_factory.mktemp("prop-base"), spike=False)


@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(dropped=st.sets(st.integers(min_value=0, max_value=23), max_size=24))
def test_prop_deleting_readings_never_toward_agree(
    dropped: set[int], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Deleting readings can only keep or lose "agree" (never create it) and never invents a
    disagreement from a calm day: the full day agrees; any deletion cannot tell."""
    world = synthetic_world(
        tmp_path_factory.mktemp("prop"), spike=False, drop_hours=tuple(sorted(dropped))
    )
    outcome = _outcome(build_version(world))
    if len(dropped) == 24:
        assert outcome == "none"  # no data, no state, no comparison
    elif dropped:
        assert outcome == "cant_tell"  # partial coverage: no data is never normal
    else:
        assert outcome == "agree"


def test_cell_pointer_row_sha_and_offset() -> None:
    result = read_table(make_source(modality="table", sha256=sha("log")), LOG, CFG)
    first, second = result.claims
    for claim, row in ((first, 0), (second, 1)):
        ev = claim.evidence
        assert isinstance(ev, TableCellPointer) and ev.row == row
        line = LOG[ev.row_byte_offset :].split(b"\n", 1)[0].rstrip(b"\r")
        assert hashlib.sha256(line).hexdigest() == ev.row_sha256  # the raw bytes of that line
        assert ev.raw_value == claim.value
    assert first.evidence.row_byte_offset == LOG.index(b"2015-07-10")  # type: ignore[union-attr]
    assert second.evidence.row_byte_offset == LOG.index(b"2015-07-11")  # type: ignore[union-attr]
    assert first.subject.entity_id == "machine:21" and second.subject.entity_id == "machine:22"


def test_envelope_refuses_without_log_coverage(tmp_path: Path) -> None:
    _write(tmp_path, "machine:21", date(2015, 6, 1), date(2015, 8, 31), 21)
    reader = ParquetTelemetryReader(tmp_path)
    undeclared = make_source("events-errors", modality="table", mime="text/csv")
    with pytest.raises(LogCoverageError):
        learn_envelopes(reader, [], [undeclared], CASE, CFG.ontology, CFG)


def test_days_outside_a_logs_coverage_are_never_quiet(tmp_path: Path) -> None:
    _write(tmp_path, "machine:21", date(2015, 6, 1), date(2015, 8, 31), 21)
    reader = ParquetTelemetryReader(tmp_path)
    everything = CoveragePeriod(start="2015-05-31T18:30:00Z", end="2015-08-31T18:30:00Z")
    june_only = CoveragePeriod(start="2015-05-31T18:30:00Z", end="2015-06-30T18:30:00Z")
    full = make_source(
        "events-errors", modality="table", mime="text/csv", coverage_period=everything
    )
    short = full.model_copy(update={"coverage_period": june_only})
    (a, *_) = learn_envelopes(reader, [], [full], CASE, CFG.ontology, CFG)
    (b, *_) = learn_envelopes(reader, [], [short], CASE, CFG.ontology, CFG)
    assert max(q.date for q in b.quiet_days) <= "2015-06-30" < max(q.date for q in a.quiet_days)
    assert b.n < a.n  # a missing log must not read as "no events"
