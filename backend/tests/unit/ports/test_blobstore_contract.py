"""BlobStore contract. Real adapters join the parametrisation later."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable

import pytest

from trace_adapters.fakes import MemBlobStore
from trace_core.errors import PayloadTooLarge
from trace_core.ports import BlobStore

FACTORIES: dict[str, Callable[[], BlobStore]] = {"fake": MemBlobStore}


@pytest.fixture(params=list(FACTORIES))
def store(request: pytest.FixtureRequest) -> BlobStore:
    return FACTORIES[request.param]()


def test_put_open_exists_round_trip(store: BlobStore) -> None:
    data = b"hello trace"
    ref = store.put(io.BytesIO(data), max_bytes=1024)
    assert ref.sha256 == hashlib.sha256(data).hexdigest() and ref.size == len(data)
    assert store.exists(ref.sha256)
    assert store.open(ref.sha256).read() == data


def test_put_existing_hash_is_noop(store: BlobStore) -> None:
    first = store.put(io.BytesIO(b"same"), max_bytes=64)
    second = store.put(io.BytesIO(b"same"), max_bytes=64)
    assert first == second and store.open(first.sha256).read() == b"same"


def test_over_cap_is_rejected_and_nothing_stored(store: BlobStore) -> None:
    data = b"x" * 100
    with pytest.raises(PayloadTooLarge):
        store.put(io.BytesIO(data), max_bytes=99)
    assert not store.exists(hashlib.sha256(data).hexdigest())


def test_exactly_at_cap_is_accepted(store: BlobStore) -> None:
    assert store.put(io.BytesIO(b"x" * 99), max_bytes=99).size == 99


def test_missing_hash(store: BlobStore) -> None:
    assert not store.exists("0" * 64)
