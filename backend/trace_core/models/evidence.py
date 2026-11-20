"""Evidence pointers (PRD 9.4) and reader-port value objects (IMPLEMENTATION_PLAN C.1, C.2)."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from trace_core.models.base import (
    CoreModel,
    DecisionId,
    EnvelopeId,
    SeriesId,
    Sha256,
    SourceId,
)
from trace_core.models.time import UtcStr

Role = Literal["viewer", "reviewer", "senior_reviewer", "ingestor", "evaluator"]


class Rect(CoreModel):
    """Axis-aligned box: x, y, width, height (points or pixels depending on context)."""

    x: float
    y: float
    w: float
    h: float


class RectPx(CoreModel):
    """Pixel rectangle (integers)."""

    x: int
    y: int
    w: int
    h: int


class Principal(CoreModel):
    """Identity from the session only (promise 9). MVP `iss` is "local"."""

    iss: str
    sub: str


class TextSpanPointer(CoreModel):
    kind: Literal["text_span"] = "text_span"
    source_id: SourceId
    sha256: Sha256
    page: int | None = None  # None for txt/md
    line: int | None = None
    page_text_sha256: Sha256
    text_canon_version: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    quote: str
    quote_sha256: Sha256
    line_rects_pt: list[Rect] | None = None
    line_rects_px: list[RectPx] | None = None

    @model_validator(mode="after")
    def _span(self) -> TextSpanPointer:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if not self.quote:
            raise ValueError("quote must not be empty")
        return self


class ImageRegionPointer(CoreModel):
    kind: Literal["image_region"] = "image_region"
    source_id: SourceId
    sha256: Sha256  # of the EXIF-oriented derived image
    bbox: Rect
    coord_space: Literal["oriented_px"] = "oriented_px"
    reader: Literal["ocr", "vlm"]
    read_text: str
    reread_text: str | None = None
    crop_sha256: Sha256


class TableCellPointer(CoreModel):
    kind: Literal["table_cell"] = "table_cell"
    source_id: SourceId
    sha256: Sha256
    row: int = Field(ge=0)
    column: str
    raw_value: str
    row_sha256: Sha256
    row_byte_offset: int = Field(ge=0)
    sheet: str | None = None


class SensorWindowPointer(CoreModel):
    kind: Literal["sensor_window"] = "sensor_window"
    source_id: SourceId
    series_id: SeriesId
    partition_sha256: Sha256
    channels: list[str]
    start: UtcStr
    end: UtcStr
    n_points: int = Field(ge=0)
    expected_points: int = Field(ge=0)
    statistic: str
    granularity: Literal["hour", "shift", "day"]
    window_sha256: Sha256
    envelope_id: EnvelopeId | None = None

    @model_validator(mode="after")
    def _window(self) -> SensorWindowPointer:
        if not self.start < self.end:
            raise ValueError("window requires start < end (half-open)")
        return self


class HumanDecisionPointer(CoreModel):
    kind: Literal["human_decision"] = "human_decision"
    decision_id: DecisionId
    principal: Principal
    display_name_snapshot: str
    role_snapshot: Role
    reason: str
    base_version: int = Field(ge=0)
    shown_evidence_hash: Sha256
    timestamp: UtcStr

    wall_clock_fields: ClassVar[frozenset[str]] = frozenset({"timestamp"})


EvidencePointer = Annotated[
    TextSpanPointer
    | ImageRegionPointer
    | TableCellPointer
    | SensorWindowPointer
    | HumanDecisionPointer,
    Field(discriminator="kind"),
]


# ------------------------------------------------------------------ reader values
class BlobRef(CoreModel):
    sha256: Sha256
    size: int = Field(ge=0)


class PageText(CoreModel):
    """Raw page text plus per-offset geometry. All per-offset lists have len(text) items.

    `text` is a Python str (code points; surrogate pairs joined). `char_to_offset[i]` maps the
    i-th PDFium char index to its offset in `text`. Generated chars are kept and flagged.
    """

    text: str
    page_text_sha256: Sha256
    text_canon_version: str
    char_to_offset: list[int]
    char_boxes_pt: list[Rect | None]
    loose_boxes_pt: list[Rect | None]
    font_sizes: list[float]
    generated: list[bool]
    text_object_ids: list[int]
    render_mode: dict[str, int] | None = None  # text object id -> PDF text render mode
    fill_alpha: dict[str, int] | None = None  # text object id -> 0..255
    capabilities: frozenset[str]
    cropbox: Rect
    rotation: int

    @model_validator(mode="after")
    def _aligned(self) -> PageText:
        n = len(self.text)
        for name in (
            "char_boxes_pt",
            "loose_boxes_pt",
            "font_sizes",
            "generated",
            "text_object_ids",
        ):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} must have one entry per text offset")
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270")
        return self


class OcrConfig(CoreModel):
    lang: str = "eng"
    psm: int = 6
    timeout_s: int = 20


class OcrWord(CoreModel):
    text: str
    bbox: Rect
    conf: float


class OcrResult(CoreModel):
    words: list[OcrWord]
    text: str
    engine_version: str
    traineddata_sha: Sha256 | None = None


class VlmReading(CoreModel):
    text: str
    model_id: str
    prompt_id: str
    confidence: float | None = None


class Proposal(CoreModel):
    """One LLM proposal. Never trusted: the 5-check verifier re-derives everything."""

    quote: str
    attribute: str
    value: str
    unit: str | None = None
    entity_mention: str | None = None
    claim_class: str | None = None


class ProposalBatch(CoreModel):
    proposals: list[Proposal]
    model_id: str
    prompt_id: str


class RedactionSpan(CoreModel):
    redacted_start: int
    redacted_end: int
    original_start: int
    original_end: int


class RedactedDocument(CoreModel):
    """Reversible span map; numbers and units are never redacted."""

    text: str
    spans: list[RedactionSpan]


class CacheKey(CoreModel):
    input_sha: Sha256
    extractor_id: str
    extractor_version: str
    params_hash: Sha256
    binary_version: str
