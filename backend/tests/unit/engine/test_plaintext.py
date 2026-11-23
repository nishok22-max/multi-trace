"""A-03: the plain-text reader. Named: test_plaintext_reader_offsets_crlf_preserved."""

from __future__ import annotations

import hashlib

import pytest

from tests.factories import make_source, sha
from tests.unit.engine.test_gaps import CFG
from trace_core.models.evidence import TextSpanPointer
from trace_core.models.time import Interval
from trace_core.read.text import read_plaintext

TEXT = (
    "Maintenance note\r\n"
    "Report date: 06 Aug 2015 09:30\r\n"
    "Reporting period: 05 Aug 2015\r\n"
    "Machine 21 ran normally through both shifts.\r\n"
    "Nothing else to report.\r\n"
)


def _read(text: str):  # type: ignore[no-untyped-def]
    return read_plaintext(make_source(sha256=sha("txt")), text.encode("utf-8"), CFG)


def test_plaintext_reader_offsets_crlf_preserved() -> None:
    (claim,) = _read(TEXT).claims
    ev = claim.evidence
    assert isinstance(ev, TextSpanPointer)
    assert TEXT[ev.char_start : ev.char_end] == ev.quote  # exact slice, CRLF untouched
    assert ev.quote == "ran normally through both shifts"
    assert ev.quote_sha256 == hashlib.sha256(ev.quote.encode()).hexdigest()
    assert ev.page_text_sha256 == hashlib.sha256(TEXT.encode()).hexdigest()
    assert ev.page == 1 and ev.line == 4  # CRLF counts as one line break
    assert claim.subject.entity_id == "machine:21"
    vt = claim.temporal.valid_time
    assert isinstance(vt, Interval) and vt.granularity == "day"


def test_lf_and_crlf_documents_give_the_same_claim_but_different_offsets() -> None:
    (crlf,) = _read(TEXT).claims
    (lf,) = _read(TEXT.replace("\r\n", "\n")).claims
    assert crlf.statement == lf.statement
    assert isinstance(crlf.evidence, TextSpanPointer) and isinstance(lf.evidence, TextSpanPointer)
    assert crlf.evidence.char_start > lf.evidence.char_start  # the extra \r characters count


def test_plaintext_has_no_visibility_fallback_flag_and_no_hidden_text_items() -> None:
    result = _read(TEXT)
    assert result.review_items == []
    assert "visibility_fallback" not in result.claims[0].confidence.components


def test_non_utf8_bytes_are_refused() -> None:
    with pytest.raises(UnicodeDecodeError):
        read_plaintext(make_source(sha256=sha("bad")), b"Machine 21 \xff\xfe ran normally", CFG)


def test_a_bom_stays_a_character_so_offsets_stay_exact() -> None:
    text = "﻿Machine 21 ran normally on this shift."
    (claim,) = _read(text).claims
    ev = claim.evidence
    assert isinstance(ev, TextSpanPointer) and text[ev.char_start : ev.char_end] == ev.quote
