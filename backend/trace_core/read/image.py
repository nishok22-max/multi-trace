"""Image reader (A-06, PRD 8.1): a gauge photo becomes an extracted numeric claim or a review item.

Pipeline: the photo is oriented and stripped of metadata by the `ImagePrep` port (decoding stays
in the build child), OCR reads the words, and rules (never a model) decide:

- the number must sit next to a unit word that names exactly one configured gauge;
- a value outside the gauge's range is `implausible_value`, and a value that would be in range
  with one decimal place less (OCR "69" for 6.9) is held the same way: it is NEVER auto-corrected;
- a second OCR read of the number's own region must agree with the first, else
  `reader_disagreement`; the claim keeps both reads on its pointer.
A photo carries no document date and no machine, so the claim is `unresolved` with unknown time and
is held until a reviewer decides (no data is never normal).
"""

from __future__ import annotations

import hashlib
import re

from trace_core.canonical import canonical_sha256
from trace_core.ids import build_claim, review_id
from trace_core.models.claims import ClaimRecord, Confidence, MentionKey, Method, Subject
from trace_core.models.config import ConfigBundle, Gauge
from trace_core.models.evidence import ImageRegionPointer, OcrConfig, OcrWord
from trace_core.models.records import ReviewItem, ReviewType, Source
from trace_core.models.time import ObservedTime, Temporal, UnknownTime
from trace_core.normalise.time import fmt_utc
from trace_core.ports import EnginePorts
from trace_core.stage_types import ReadResult

NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")


def _same_line(a: OcrWord, b: OcrWord) -> bool:
    return abs((a.bbox.y + a.bbox.h / 2) - (b.bbox.y + b.bbox.h / 2)) <= max(a.bbox.h, b.bbox.h)


def _pairs(words: list[OcrWord]) -> list[tuple[OcrWord, OcrWord]]:
    ordered = sorted(words, key=lambda w: (round(w.bbox.y), w.bbox.x))
    return [
        (a, b)
        for a, b in zip(ordered, ordered[1:], strict=False)
        if NUMBER.match(a.text) and _same_line(a, b) and a.bbox.x < b.bbox.x
    ]


def _review(
    src: Source, kind: ReviewType, number: OcrWord, why: dict[str, object], opened_at: str
) -> ReviewItem:
    key = MentionKey(
        source_sha256=src.sha256, locator=f"img:{round(number.bbox.x)},{round(number.bbox.y)}"
    )
    return ReviewItem(
        review_id=review_id(kind, [key]),
        type=kind,
        claim_ids=[],
        mention_keys=[key],
        evidence_hash=canonical_sha256({"key": key, "read": number.text, "why": why}),
        opened_at=opened_at,
    )


def read_image(src: Source, blob: bytes, cfg: ConfigBundle, ports: EnginePorts) -> ReadResult:
    opened_at = fmt_utc(ports.clock.now_utc())
    prep = ports.image_prep
    if prep is None:
        key = MentionKey(source_sha256=src.sha256, locator="img:unsupported")
        item = ReviewItem(
            review_id=review_id("unsupported_page", [key]),
            type="unsupported_page",
            claim_ids=[],
            mention_keys=[key],
            evidence_hash=canonical_sha256({"key": key, "why": "no image decoder"}),
            opened_at=opened_at,
        )
        return ReadResult(claims=[], review_items=[item])  # fail closed
    oriented = prep.orient(blob)
    oriented_sha = hashlib.sha256(oriented).hexdigest()
    result = ports.ocr.read_words(oriented, OcrConfig())
    claims: list[ClaimRecord] = []
    items: list[ReviewItem] = []
    by_unit: dict[str, list[Gauge]] = {}
    for gauge in cfg.gauges:
        by_unit.setdefault(gauge.unit.casefold(), []).append(gauge)
    for number, unit_word in _pairs(result.words):
        gauges = by_unit.get(unit_word.text.casefold(), [])
        if len(gauges) != 1:
            continue  # an unknown or ambiguous unit word is not a reading
        gauge = gauges[0]
        text = number.text
        value = float(text.replace(",", "."))
        if not gauge.min_value <= value <= gauge.max_value:
            dropped = (
                "." not in text
                and "," not in text
                and (gauge.min_value <= value / 10 <= gauge.max_value)
            )
            why = {"gauge": gauge.gauge_id, "value": value, "decimal_point_dropped": dropped}
            items.append(_review(src, "implausible_value", number, why, opened_at))
            continue
        again = ports.ocr.reread_region(oriented, number.bbox, OcrConfig())
        reread = again.text.strip()
        if reread != text:
            why = {"gauge": gauge.gauge_id, "first": text, "second": reread}
            items.append(_review(src, "reader_disagreement", number, why, opened_at))
            continue
        prior = cfg.gate.image_extractor_prior
        claims.append(
            build_claim(
                case_id=src.case_id,
                claim_type="extracted",
                statement=f"Gauge {gauge.gauge_id} reads {text} {gauge.unit}",
                subject=Subject(entity_id=None, link_status="unresolved"),
                attribute=gauge.attribute,
                value=value,
                value_type="numeric",
                unit=gauge.unit,
                unit_status="known",
                temporal=Temporal(
                    valid_time=UnknownTime(reason="the photo has no document date"),
                    observed_time=ObservedTime(at=None, basis="document_date"),
                    timezone_original=cfg.case.plant_tz,
                ),
                modality="image",
                evidence=ImageRegionPointer(
                    source_id=src.source_id,
                    sha256=oriented_sha,
                    bbox=number.bbox,
                    reader="ocr",
                    read_text=text,
                    reread_text=reread,
                    crop_sha256=prep.crop_sha256(oriented, number.bbox),
                ),
                derived_from=[],
                method=Method(
                    extractor="ocr:gauge_digits", extractor_version="1", rule_id="image.gauge"
                ),
                confidence=Confidence(
                    value=prior,
                    calibrated=False,
                    components={"extractor": prior},
                    stage="pre",
                    note="uncalibrated raw pre-score: OCR prior only",
                ),
            )
        )
    return ReadResult(claims=claims, review_items=items)
