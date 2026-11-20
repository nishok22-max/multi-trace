"""TelemetryReader contract (fake now; the Parquet adapter joins in M2)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from trace_adapters.fakes import FakeTelemetryReader
from trace_core.ports import TableLike, TelemetryReader

HOURS = [f"2015-03-14T{h:02d}:00:00Z" for h in range(24)]
SERIES = {"telemetry/machine:21": {"ts": HOURS, "vibration": [float(h) for h in range(24)]}}
FACTORIES: dict[str, Callable[[], TelemetryReader]] = {
    "fake": lambda: FakeTelemetryReader(
        {k: {c: list(v) for c, v in d.items()} for k, d in SERIES.items()}
    ),
}


@pytest.fixture(params=list(FACTORIES))
def reader(request: pytest.FixtureRequest) -> TelemetryReader:
    return FACTORIES[request.param]()


def test_read_is_half_open(reader: TelemetryReader) -> None:
    table = reader.read("telemetry/machine:21", "2015-03-14T02:00:00Z", "2015-03-14T05:00:00Z")
    assert isinstance(table, TableLike)
    assert table.to_pydict()["ts"] == HOURS[2:5]  # start included, end excluded


def test_empty_window(reader: TelemetryReader) -> None:
    assert (
        reader.read("telemetry/machine:21", "2016-01-01T00:00:00Z", "2016-01-02T00:00:00Z").num_rows
        == 0
    )


def test_unknown_series_fails_closed(reader: TelemetryReader) -> None:
    with pytest.raises(KeyError):
        reader.read("telemetry/machine:99", "2015-03-14T00:00:00Z", "2015-03-15T00:00:00Z")


def test_partition_sha_is_stable_and_content_sensitive(reader: TelemetryReader) -> None:
    sha = reader.partition_sha("telemetry/machine:21")
    assert sha == reader.partition_sha("telemetry/machine:21") and len(sha) == 64
    changed = FakeTelemetryReader({"telemetry/machine:21": {"ts": HOURS, "vibration": [1.0] * 24}})
    assert changed.partition_sha("telemetry/machine:21") != sha


def test_duplicates_are_preserved_not_averaged(reader: TelemetryReader) -> None:
    dup = FakeTelemetryReader({"s": {"ts": [HOURS[0], HOURS[0]], "v": [1.0, 9.0]}})
    assert dup.read("s", HOURS[0], HOURS[1]).to_pydict()["v"] == [1.0, 9.0]
