"""ExtractionCache contract: write-once, and a replay-mode miss is an error."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Literal

import pytest

from tests.factories import sha
from trace_adapters.fakes import DictExtractionCache
from trace_core.errors import CacheModeError, CacheWriteOnceViolation, ReplayCacheMiss
from trace_core.models.evidence import CacheKey
from trace_core.ports import ExtractionCache

Factory = Callable[[Literal["record", "replay"]], ExtractionCache]
FACTORIES: dict[str, Factory] = {"fake": lambda mode: DictExtractionCache(mode)}
KEY = CacheKey(
    input_sha=sha("in"),
    extractor_id="pdfium.page_text",
    extractor_version="1",
    params_hash=sha("params"),
    binary_version="pypdfium2 4.30.0",
)


@pytest.fixture(params=list(FACTORIES))
def make(request: pytest.FixtureRequest) -> Factory:
    return FACTORIES[request.param]


def test_record_mode_miss_returns_none(make: Factory) -> None:
    cache = make("record")
    assert cache.mode == "record" and cache.get(KEY) is None


def test_put_returns_artifact_sha_and_get_hits(make: Factory) -> None:
    cache = make("record")
    assert cache.put(KEY, b"artifact") == hashlib.sha256(b"artifact").hexdigest()
    assert cache.get(KEY) == b"artifact"


def test_write_once_same_bytes_ok_different_bytes_raise(make: Factory) -> None:
    cache = make("record")
    cache.put(KEY, b"v1")
    assert cache.put(KEY, b"v1") == hashlib.sha256(b"v1").hexdigest()  # idempotent
    with pytest.raises(CacheWriteOnceViolation):
        cache.put(KEY, b"v2")
    assert cache.get(KEY) == b"v1"  # the original is untouched


def test_keys_differing_in_any_component_are_distinct(make: Factory) -> None:
    cache = make("record")
    cache.put(KEY, b"a")
    other = KEY.model_copy(update={"binary_version": "pypdfium2 5.0.0"})
    assert cache.get(other) is None
    cache.put(other, b"b")
    assert cache.get(KEY) == b"a" and cache.get(other) == b"b"


def test_replay_miss_is_an_error_not_none(make: Factory) -> None:
    cache = make("replay")
    assert cache.mode == "replay"
    with pytest.raises(ReplayCacheMiss):
        cache.get(KEY)


def test_replay_mode_is_read_only(make: Factory) -> None:
    with pytest.raises(CacheModeError):
        make("replay").put(KEY, b"x")


def test_recorded_entries_replay_identically() -> None:
    recorded = DictExtractionCache("record")
    recorded.put(KEY, b"artifact")
    replay = recorded.replay_view()
    assert replay.mode == "replay" and replay.get(KEY) == b"artifact"
    with pytest.raises(ReplayCacheMiss):
        replay.get(KEY.model_copy(update={"extractor_version": "2"}))
