"""Test factories: small valid objects. Not production code."""

from __future__ import annotations

import hashlib
from typing import Any

from trace_core.ids import build_claim, decision_id, review_event_id, review_id
from trace_core.models.case import (
    Case,
    CaseState,
    CaseVersion,
    Story,
    VersionRecords,
    Views,
)
from trace_core.models.claims import MentionKey
from trace_core.models.evidence import PageText, Principal, Rect
from trace_core.models.records import (
    Choice,
    Decision,
    EntityChoice,
    ReviewEvent,
    ReviewItem,
    Source,
)

CASE_ID = "case-m21-0314"
NOW = "2015-03-15T09:10:00Z"


def sha(n: object) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


def make_case(case_id: str = CASE_ID) -> Case:
    return Case(
        case_id=case_id,
        title="Machine 21, 14 March 2015",
        entities=["machine:21"],
        window_start="2015-03-13T18:30:00Z",
        window_end="2015-03-14T18:30:00Z",
        plant_tz="Asia/Kolkata",
        created_at=NOW,
    )


def make_source(source_id: str = "src-report-0314", case_id: str = CASE_ID, **over: Any) -> Source:
    fields: dict[str, Any] = {
        "source_id": source_id,
        "case_id": case_id,
        "modality": "text",
        "sha256": sha(source_id),
        "origin": "authored-maintenance-report",
        "ingested_at": NOW,
        "synthetic": True,
        "mime": "application/pdf",
        "size": 1234,
    }
    return Source(**{**fields, **over})


def text_pointer(n: int = 0, *, source_id: str = "src-report-0314") -> dict[str, Any]:
    quote = f"ran normally through both shifts {n}"
    return {
        "kind": "text_span",
        "source_id": source_id,
        "sha256": sha(source_id),
        "page": 1,
        "line": 4,
        "page_text_sha256": sha("page-text"),
        "text_canon_version": "1",
        "char_start": 10 + n,
        "char_end": 10 + n + len(quote),
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
    }


def claim_fields(n: int = 0, **over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "label": f"C-{n}",
        "case_id": CASE_ID,
        "claim_type": "extracted",
        "statement": "Machine 21 ran normally through both shifts",
        "subject": {
            "mention": "Machine 21",
            "entity_id": "machine:21",
            "link_status": "resolved",
            "mention_key": {"source_sha256": sha("src-report-0314"), "locator": f"p1:{n}"},
        },
        "attribute": "operating_state",
        "value": "normal",
        "value_type": "categorical",
        "unit": None,
        "unit_status": "not_applicable",
        "temporal": {
            "valid_time": {
                "start": "2015-03-13T18:30:00Z",
                "end": "2015-03-14T18:30:00Z",
                "granularity": "day",
                "resolved_from": "explicit",
            },
            "observed_time": {"at": NOW, "basis": "document_date"},
            "timezone_original": "Asia/Kolkata",
        },
        "modality": "text",
        "evidence": text_pointer(n),
        "derived_from": [],
        "method": {
            "extractor": "rules:phrase_list_v2",
            "extractor_version": "2.0.0",
            "rule_id": "status.normal",
        },
        "confidence": {"value": 0.5, "calibrated": False, "components": {"extractor": 0.5}},
        "created_at": NOW,
    }
    return {**fields, **over}


def make_claim(n: int = 0, **over: Any):  # type: ignore[no-untyped-def]
    return build_claim(**claim_fields(n, **over))


def make_review_item(claim_ids: list[str], n: int = 0, review_type: str = "ambiguous_entity"):  # type: ignore[no-untyped-def]
    keys = [MentionKey(source_sha256=sha("src-report-0314"), locator=f"p1:{n}")]
    return ReviewItem(
        review_id=review_id(review_type, keys),
        type=review_type,  # type: ignore[arg-type]
        claim_ids=claim_ids,
        mention_keys=keys,
        evidence_hash=sha(f"evidence-{n}"),
        opened_at=NOW,
    )


def opened_event(item: ReviewItem) -> ReviewEvent:
    return ReviewEvent(
        event_id=review_event_id(item.review_id, "opened", 0),
        seq=0,
        review_id=item.review_id,
        kind="opened",
        at=NOW,
    )


def make_decision(
    item: ReviewItem,
    choice: Choice | None = None,
    *,
    base_version: int = 1,
    evidence_hash: str | None = None,
    supersedes: str | None = None,
    sub: str = "reviewer1",
) -> Decision:
    choice = choice or EntityChoice(entity_id="machine:21")
    principal = Principal(iss="local", sub=sub)
    return Decision(
        decision_id=decision_id(item.review_id, principal, base_version, choice),
        case_id=CASE_ID,
        review_id=item.review_id,
        principal=principal,
        display_name_snapshot="A. Reviewer",
        role_snapshot="reviewer",
        choice=choice,
        reason="Line 2 has M-21; serial matches the register",
        base_version=base_version,
        shown_evidence_hash=evidence_hash or item.evidence_hash,
        supersedes=supersedes,  # type: ignore[arg-type]
        at=NOW,
    )


def decision_event(decision: Decision, seq: int) -> ReviewEvent:
    from trace_core.review.rules import event_kind_for

    kind = event_kind_for(decision.choice)
    return ReviewEvent(
        event_id=review_event_id(decision.review_id, kind, seq),
        seq=seq,
        review_id=decision.review_id,
        kind=kind,
        decision_id=decision.decision_id,
        at=NOW,
    )


def make_version(
    version: int,
    parent: CaseVersion | None,
    records: VersionRecords | None = None,
    case_id: str = CASE_ID,
) -> CaseVersion:
    records = records or VersionRecords(
        claims=[], comparisons=[], conflicts=[], envelopes=[], review_items=[], decisions=[]
    )
    manifest = sha(f"manifest-{case_id}-{version}-{len(records.claims)}-{len(records.decisions)}")
    state = CaseState(
        case_id=case_id,
        version=version,
        manifest_hash=manifest,
        plant_tz="Asia/Kolkata",
        scope_entities=["machine:21"],
        window_start="2015-03-13T18:30:00Z",
        window_end="2015-03-14T18:30:00Z",
        sources=[],
        claim_ids=[c.claim_id for c in records.claims],
        comparison_ids=[],
        conflict_ids=[],
        gap_claim_ids=[],
        decision_ids=[d.decision_id for d in records.decisions],
        review_ids=[r.review_id for r in records.review_items],
    )
    return CaseVersion(
        case_id=case_id,
        version=version,
        parent_manifest_hash=parent.manifest_hash if parent else None,
        manifest_hash=manifest,
        config_hash=sha("config"),
        engine_sha="engine-test",
        lockfile_hash=sha("lock"),
        canon_version="1",
        tesseract_version="n/a",
        traineddata_sha="n/a",
        pdfium_version="n/a",
        tzdata_version="n/a",
        llm_mode="off",
        ai_status="off",
        records=records,
        views=Views(state=state, story=Story(steps=[]), timeline=[], review=[]),
        created_at=NOW,
    )


def make_page_text(text: str = "Machine 21 ran normally") -> PageText:
    n = len(text)
    box = Rect(x=72.0, y=700.0, w=6.0, h=10.0)
    return PageText(
        text=text,
        page_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_canon_version="1",
        char_to_offset=list(range(n)),
        char_boxes_pt=[box] * n,
        loose_boxes_pt=[box] * n,
        font_sizes=[12.0] * n,
        generated=[False] * n,
        text_object_ids=[-1] * n,
        capabilities=frozenset({"char_loop"}),
        cropbox=Rect(x=0.0, y=0.0, w=595.0, h=842.0),
        rotation=0,
    )
