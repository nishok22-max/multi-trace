"""Ports (IMPLEMENTATION_PLAN C.2): `typing.Protocol` interfaces the pure core depends on.

The core never imports an adapter. Adapters implement these structurally and pass the shared
contract tests in `tests/unit/ports/`.

Telemetry tables are typed as the structural `TableLike` because `pyarrow` is forbidden in
`trace_core`; `pyarrow.Table` satisfies it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Literal, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from trace_core.models.case import Case, CaseVersion, VersionMembers
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import Gauge
from trace_core.models.evidence import (
    BlobRef,
    CacheKey,
    OcrConfig,
    OcrResult,
    PageText,
    ProposalBatch,
    Rect,
    RectPx,
    RedactedDocument,
    VlmReading,
)
from trace_core.models.records import (
    ComparisonRecord,
    ConflictRecord,
    Decision,
    Envelope,
    ReviewEvent,
    ReviewItem,
    Source,
)
from trace_core.models.time import UtcStr


@runtime_checkable
class TableLike(Protocol):
    """Minimal structural view of a columnar table (satisfied by `pyarrow.Table`)."""

    @property
    def num_rows(self) -> int: ...

    @property
    def column_names(self) -> list[str]: ...

    def to_pydict(self) -> dict[str, list[Any]]: ...


@dataclass(frozen=True)
class RenderResult:
    png: bytes
    gray: NDArray[np.uint8]


@dataclass(frozen=True)
class Committed:
    version: int
    manifest_hash: str


@dataclass(frozen=True)
class Moved:
    """The latest version moved since `expected_latest`: recompute and retry."""

    latest: int


AppendableRecord = (
    Case
    | Source
    | ClaimRecord
    | ComparisonRecord
    | ConflictRecord
    | Envelope
    | ReviewItem
    | ReviewEvent
)


class BlobStore(Protocol):
    def put(self, stream: BinaryIO, *, max_bytes: int) -> BlobRef:
        """Store the stream. Existing hash: no-op. Over `max_bytes`: PayloadTooLarge."""
        ...

    def open(self, sha: str) -> BinaryIO: ...

    def exists(self, sha: str) -> bool: ...


class PdfReader(Protocol):
    def page_count(self, pdf: bytes) -> int: ...

    def page_text(self, pdf: bytes, page: int) -> PageText: ...

    def render_png(
        self,
        pdf: bytes,
        page: int,
        dpi: int = 150,
        *,
        without_objects: frozenset[int] = frozenset(),
    ) -> RenderResult: ...

    def pt_to_px(self, meta: PageText, rect: Rect, dpi: int) -> RectPx:
        """Child-only adapter."""
        ...


class OcrReader(Protocol):
    def read_words(self, png: bytes, cfg: OcrConfig) -> OcrResult: ...

    def reread_region(self, png: bytes, bbox: Rect, cfg: OcrConfig) -> OcrResult: ...


class TelemetryReader(Protocol):
    def read(self, series_id: str, start: UtcStr, end: UtcStr) -> TableLike: ...

    def partition_sha(self, series_id: str) -> str: ...


class VlmReader(Protocol):
    """P1."""

    def read_region(self, crop_png: bytes, prompt_id: str, gauge: Gauge) -> VlmReading: ...


class LlmProposer(Protocol):
    def propose(self, doc: RedactedDocument, prompt_id: str) -> ProposalBatch: ...


class Redactor(Protocol):
    def redact(self, text: str) -> RedactedDocument:
        """Reversible span map; numbers and units are never redacted."""
        ...


class ExtractionCache(Protocol):
    """Reader outputs, keyed by CacheKey. Write-once. A replay-mode miss raises ReplayCacheMiss."""

    @property
    def mode(self) -> Literal["record", "replay"]: ...

    def get(self, key: CacheKey) -> bytes | None: ...

    def put(self, key: CacheKey, artifact: bytes) -> str: ...


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class ClaimStore(Protocol):
    def append(self, case_id: str, records: Sequence[AppendableRecord]) -> None:
        """Append-only. Re-appending identical content is a no-op; differing content raises."""
        ...

    def put_version(self, version: CaseVersion, members: VersionMembers) -> None: ...

    def get_version(self, case_id: str, version: int) -> CaseVersion | None: ...

    def latest(self, case_id: str) -> CaseVersion | None: ...

    def load_claims(self, case_id: str, version: int) -> list[ClaimRecord]: ...

    def review_events(self, case_id: str, review_id: str | None = None) -> list[ReviewEvent]: ...

    def commit_decision(
        self,
        case_id: str,
        expected_latest: int,
        decision: Decision,
        event: ReviewEvent,
        version: CaseVersion,
    ) -> Committed | Moved:
        """Short BEGIN IMMEDIATE re-check, then insert. Raises AlreadyDecided / EvidenceChanged."""
        ...


@dataclass(frozen=True)
class EnginePorts:
    blobs: BlobStore
    pdf: PdfReader
    ocr: OcrReader
    telemetry: TelemetryReader
    cache: ExtractionCache
    clock: Clock
    llm: LlmProposer
    redactor: Redactor
    vlm: VlmReader | None = None
