"""In-memory fakes for every port (A-01b). Real adapters pass the same contract tests."""

from trace_adapters.fakes.blob import MemBlobStore
from trace_adapters.fakes.cache import DictExtractionCache
from trace_adapters.fakes.claim_store import MemClaimStore
from trace_adapters.fakes.clock import FixedClock
from trace_adapters.fakes.llm import FakeLlm, IdentityRedactor
from trace_adapters.fakes.ocr import FakeOcr
from trace_adapters.fakes.pdf import FakePdfReader
from trace_adapters.fakes.telemetry import FakeTelemetryReader

__all__ = [
    "DictExtractionCache",
    "FakeLlm",
    "FakeOcr",
    "FakePdfReader",
    "FakeTelemetryReader",
    "FixedClock",
    "IdentityRedactor",
    "MemBlobStore",
    "MemClaimStore",
]
