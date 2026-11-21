"""Text readers (A-03 minimal).

`read_text` turns the "ran normally" family of phrases in a PDF page into EXTRACTED claims with
an exact `TextSpanPointer` (offsets into the hashed page text, quote, quote_sha256).

Not in M2 (do not fake): TODO(M3/A-04) hidden-text guard; TODO(M3/A-05) page cap, review items
and the extraction cache for `PageText`; TODO(M3) relative dates, the entity resolver and the
LLM verifier. `read_plaintext` is M3.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from trace_core.ids import build_claim
from trace_core.models.claims import Candidate, ClaimRecord, Confidence, MentionKey, Method, Subject
from trace_core.models.config import ConfigBundle, PhraseRule
from trace_core.models.evidence import PageText, Rect, TextSpanPointer
from trace_core.models.records import Source
from trace_core.models.time import Interval, ObservedTime, Temporal, UnknownTime
from trace_core.normalise.time import day_interval, local_naive_to_utc
from trace_core.ports import EnginePorts
from trace_core.read.dates import find_labelled_date
from trace_core.stage_types import ReadResult

MIN_QUOTE_CHARS = 12
"""Verifier rule 2 (PRD 12 / AGENTS promise 2): a quote must be unique and at least this long."""

PERIOD_LABEL = "Reporting period"
WRITTEN_LABEL = "Report date"

# phrase class -> claim value. Classes not listed here are M3 (stop / vibration / pressure).
_CLASS_VALUE = {"operating_normal": "normal"}


def read_text(src: Source, blob: bytes, cfg: ConfigBundle, ports: EnginePorts) -> ReadResult:
    claims: list[ClaimRecord] = []
    for index in range(ports.pdf.page_count(blob)):
        page = ports.pdf.page_text(blob, index)
        claims.extend(_page_claims(src, page, index + 1, cfg))
    return ReadResult(claims=claims)


def read_plaintext(src: Source, blob: bytes, cfg: ConfigBundle) -> ReadResult:
    raise NotImplementedError("M3")


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


def _page_claims(src: Source, page: PageText, number: int, cfg: ConfigBundle) -> list[ClaimRecord]:
    text = page.text
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
                        components={"extractor": prior},
                        stage="pre",
                        note=(
                            "uncalibrated raw pre-score: extractor prior only; the entity-link,"
                            " time and unit components arrive with the M3 resolver"
                        ),
                    ),
                )
            )
    return out
