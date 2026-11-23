"""Text readers (A-03 minimal).

`read_text` turns the "ran normally" family of phrases in a PDF page into EXTRACTED claims with
an exact `TextSpanPointer` (offsets into the hashed page text, quote, quote_sha256).

Hidden-text guard: read/hidden_text.py. Not yet (do not fake): TODO(M3/A-05) page cap, review items
and the extraction cache for `PageText`; TODO(M3) relative dates, the entity resolver and the
LLM verifier. `read_plaintext` is M3.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from trace_core.canonical import canonical_sha256
from trace_core.errors import CapabilityMissing, RenderRefused
from trace_core.ids import build_claim, review_id
from trace_core.models.claims import Candidate, ClaimRecord, Confidence, MentionKey, Method, Subject
from trace_core.models.config import ConfigBundle, PhraseRule
from trace_core.models.evidence import PageText, Rect, TextSpanPointer
from trace_core.models.records import ReviewItem, ReviewType, Source
from trace_core.models.time import Interval, ObservedTime, Temporal, UnknownTime
from trace_core.normalise.time import day_interval, fmt_utc, local_naive_to_utc
from trace_core.ports import EnginePorts
from trace_core.read.dates import find_labelled_date
from trace_core.read.hidden_text import RENDER_DPI, CropFn, hidden_reasons
from trace_core.stage_types import ReadResult

MAX_PAGES = 50
"""A document with more pages is held whole (PRD 8.1, `pdf-page-cap`)."""
MIN_QUOTE_CHARS = 12
"""Verifier rule 2 (PRD 12 / AGENTS promise 2): a quote must be unique and at least this long."""

PERIOD_LABEL = "Reporting period"
WRITTEN_LABEL = "Report date"

# phrase class -> claim value. `machine_stopped` is not read yet: its scope (rotate) shares the
# operating_state group with the all-channel phrases and needs its own sensor claim.
_CLASS_VALUE = {
    "operating_normal": "normal",
    "vibration_high": "high",
    "pressure_low": "low",
}


def read_text(src: Source, blob: bytes, cfg: ConfigBundle, ports: EnginePorts) -> ReadResult:
    claims: list[ClaimRecord] = []
    items: dict[str, ReviewItem] = {}
    opened_at = fmt_utc(ports.clock.now_utc())
    pages = ports.pdf.page_count(blob)
    if pages > MAX_PAGES:  # the cap is enforced in the child, before any page is decoded
        return ReadResult(
            claims=[], review_items=[_page_item(src, "pdf_page_cap", 0, "cap", opened_at)]
        )
    for index in range(pages):
        page = ports.pdf.page_text(blob, index)
        if page.rotation != 0:  # rotated pages are unsupported (P1-10): held, never guessed
            items[f"u{index}"] = _page_item(
                src, "unsupported_page", index + 1, "rotated", opened_at
            )
            continue
        if not page.text.strip():  # a scanned page: no text layer to quote (OCR is P1-10)
            items[f"n{index}"] = _page_item(src, "no_text_layer", index + 1, "empty", opened_at)
            continue
        crop = _cropper(ports, blob, index, page)
        got, hidden = _page_claims(src, page, index + 1, cfg, crop, opened_at)
        claims.extend(got)
        items.update({i.review_id: i for i in hidden})
    items = {i.review_id: i for i in items.values()}
    return ReadResult(claims=claims, review_items=[items[k] for k in sorted(items)])


def _cropper(ports: EnginePorts, blob: bytes, index: int, page: PageText) -> CropFn:
    """Grey pixels of a rectangle; the page is rendered once, on first use, in the build child."""
    cache: dict[str, NDArray[np.uint8]] = {}

    def crop(rect: Rect) -> NDArray[np.uint8] | None:
        if "gray" not in cache:
            try:
                cache["gray"] = ports.pdf.render_png(blob, index, RENDER_DPI).gray
            except RenderRefused as exc:
                raise CapabilityMissing("page too large to render") from exc
        gray = cache["gray"]
        px = ports.pdf.pt_to_px(page, rect, RENDER_DPI)
        y0, y1 = max(0, px.y), min(gray.shape[0], px.y + px.h)
        x0, x1 = max(0, px.x), min(gray.shape[1], px.x + px.w)
        if y1 <= y0 or x1 <= x0:
            return None
        return gray[y0:y1, x0:x1]

    return crop


def plain_page(text: str) -> PageText:
    """A plain-text document as a one-page `PageText`: offsets are into the decoded text exactly
    as stored (CRLF kept, no normalisation); there is no geometry."""
    n = len(text)
    return PageText(
        text=text,
        page_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_canon_version="1",
        char_to_offset=list(range(n)),
        char_boxes_pt=[None] * n,
        loose_boxes_pt=[None] * n,
        font_sizes=[0.0] * n,
        generated=[False] * n,
        text_object_ids=[-1] * n,
        capabilities=frozenset(),
        cropbox=Rect(x=0.0, y=0.0, w=1.0, h=1.0),
        rotation=0,
    )


def read_plaintext(src: Source, blob: bytes, cfg: ConfigBundle, opened_at: str = "") -> ReadResult:
    """TXT / MD documents. Strict UTF-8 (a BOM is kept as a character, never stripped, so the
    offsets stay exact); undecodable bytes are refused (fail closed)."""
    text = blob.decode("utf-8")
    got, _ = _page_claims(
        src, plain_page(text), 1, cfg, _no_crop, opened_at, visible_by_nature=True
    )
    return ReadResult(claims=got)


def _no_crop(_: Rect) -> NDArray[np.uint8] | None:
    raise CapabilityMissing("plain text has no rendered pixels")


def _alias_names(cfg: ConfigBundle) -> list[tuple[str, str]]:
    """(surface form, entity_id), longest first so 'machine #21' beats 'M21'."""
    names = [
        (name, entry.entity_id)
        for entry in cfg.aliases
        for name in (entry.canonical_name, *entry.aliases)
    ]
    return sorted(names, key=lambda n: (-len(n[0]), n[0]))


def _line_start(text: str, offset: int) -> int:
    return max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1


def _sentence_end(text: str, start: int) -> int:
    ends = [i for i in (text.find(c, start) for c in (".", "\r", "\n")) if i != -1]
    end = min(ends) if ends else len(text)
    while end > start and text[end - 1] == " ":
        end -= 1
    return end


def _union_rect(page: PageText, start: int, end: int) -> list[Rect] | None:
    boxes = [b for b in page.char_boxes_pt[start:end] if b is not None]
    if not boxes:
        return None
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.x + b.w for b in boxes)
    y1 = max(b.y + b.h for b in boxes)
    return [Rect(x=x0, y=y0, w=x1 - x0, h=y1 - y0)]


def _subject(src: Source, page: PageText, number: int, start: int, cfg: ConfigBundle) -> Subject:
    text = page.text
    line_start = _line_start(text, start)
    prefix = text[line_start:start]
    for name, entity_id in _alias_names(cfg):
        hits = list(re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", prefix, re.IGNORECASE))
        if hits:
            hit = hits[-1]
            at = line_start + hit.start()
            return Subject(
                mention=prefix[hit.start() : hit.end()],
                entity_id=entity_id,
                link_status="resolved",
                candidates=[
                    Candidate(entity_id=entity_id, score=1.0, reasons=["exact alias"]),
                ],
                mention_key=MentionKey(
                    source_sha256=src.sha256, locator=f"p{number}:{at}-{at + len(hit.group(0))}"
                ),
            )
    # No registered alias: keep the last "<name> <number>" on the line as an unlinked mention for
    # the entity resolver (B-06), with a stable key so a reviewer's decision can attach to it.
    loose = list(re.finditer(r"[A-Za-z]+[ \-]?#?\d+", prefix))
    if loose:
        hit = loose[-1]
        at = line_start + hit.start()
        return Subject(
            mention=hit.group(0),
            entity_id=None,
            link_status="unresolved",
            mention_key=MentionKey(
                source_sha256=src.sha256, locator=f"p{number}:{at}-{at + len(hit.group(0))}"
            ),
        )
    return Subject(mention=None, entity_id=None, link_status="unresolved")


def _temporal(page: PageText, cfg: ConfigBundle) -> tuple[Temporal, str | None]:
    tz = cfg.case.plant_tz
    period = find_labelled_date(page.text, PERIOD_LABEL)
    written = find_labelled_date(page.text, WRITTEN_LABEL)
    valid: Interval | UnknownTime
    if period is None:
        valid = UnknownTime(reason="no reporting period in the document")
        day_text = None
    else:
        valid = day_interval(period.day, tz, "explicit")
        day_text = period.day.strftime("%d %b %Y")
    at = None
    if written is not None and written.at is not None:
        at = local_naive_to_utc(datetime.combine(written.day, written.at), tz)
    return (
        Temporal(
            valid_time=valid,
            observed_time=ObservedTime(at=at, basis="document_date"),
            timezone_original=tz,
        ),
        day_text,
    )


def _page_item(src: Source, kind: ReviewType, number: int, why: str, opened_at: str) -> ReviewItem:
    key = MentionKey(source_sha256=src.sha256, locator=f"p{number}:0-0")
    return ReviewItem(
        review_id=review_id(kind, [key]),
        type=kind,
        claim_ids=[],
        mention_keys=[key],
        evidence_hash=canonical_sha256({"key": key, "why": why}),
        opened_at=opened_at,
    )


def _hidden_item(
    src: Source, number: int, start: int, end: int, quote: str, reasons: list[str], opened_at: str
) -> ReviewItem:
    key = MentionKey(source_sha256=src.sha256, locator=f"p{number}:{start}-{end}")
    return ReviewItem(
        review_id=review_id("hidden_text", [key]),
        type="hidden_text",
        claim_ids=[],
        mention_keys=[key],
        evidence_hash=canonical_sha256(
            {"key": key, "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(), "why": reasons}
        ),
        opened_at=opened_at,
    )


def _page_claims(
    src: Source,
    page: PageText,
    number: int,
    cfg: ConfigBundle,
    crop: CropFn,
    opened_at: str,
    *,
    visible_by_nature: bool = False,
) -> tuple[list[ClaimRecord], list[ReviewItem]]:
    text = page.text
    hidden_items: list[ReviewItem] = []
    fallback = not visible_by_nature and "text_object" not in page.capabilities
    temporal, day_text = _temporal(page, cfg)
    prior = cfg.gate.text_extractor_prior
    out: list[ClaimRecord] = []
    rules: list[PhraseRule] = sorted(cfg.ontology.phrases, key=lambda r: (-len(r.phrase), r.phrase))
    for rule in rules:
        value = _CLASS_VALUE.get(rule.phrase_class)
        if value is None:
            continue
        for match in re.finditer(re.escape(rule.phrase), text, re.IGNORECASE):
            start = match.start()
            end = _sentence_end(text, start)
            quote = text[start:end]
            if len(quote) < MIN_QUOTE_CHARS or text.count(quote) != 1:
                continue  # verifier rule 2; TODO(M3) open a review item instead of skipping
            line = _line_start(text, start)
            why = [] if visible_by_nature else hidden_reasons(page, line, end, crop)
            if why:  # any invisible character on the line holds the span: 0 claims, 1 review item
                hidden_items.append(
                    _hidden_item(src, number, line, end, text[line:end], why, opened_at)
                )
                continue
            subject = _subject(src, page, number, start, cfg)
            who = subject.mention or "Unresolved subject"
            when = f" on {day_text}" if day_text else ""
            out.append(
                build_claim(
                    case_id=src.case_id,
                    claim_type="extracted",
                    statement=f"{who} {quote}{when}",
                    subject=subject,
                    attribute=rule.attribute_group,
                    value=value,
                    value_type="categorical",
                    unit=None,
                    unit_status="not_applicable",
                    temporal=temporal,
                    modality="text",
                    evidence=TextSpanPointer(
                        source_id=src.source_id,
                        sha256=src.sha256,
                        page=number,
                        line=text.count("\n", 0, start) + 1,
                        page_text_sha256=page.page_text_sha256,
                        text_canon_version=page.text_canon_version,
                        char_start=start,
                        char_end=end,
                        quote=quote,
                        quote_sha256=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                        line_rects_pt=_union_rect(page, start, end),
                    ),
                    derived_from=[],
                    method=Method(
                        extractor="rules:phrase_list",
                        extractor_version="1",
                        rule_id=f"phrase.{rule.phrase_class}",
                    ),
                    confidence=Confidence(
                        value=prior,
                        calibrated=False,
                        components={"extractor": prior}
                        | ({"visibility_fallback": 1.0} if fallback else {}),
                        stage="pre",
                        note=(
                            "uncalibrated raw pre-score: extractor prior only; the entity-link,"
                            " time and unit components arrive with the M3 resolver"
                        ),
                    ),
                )
            )
    return out, hidden_items
