"""Entity resolution (B-06, PRD 10.1). Rules decide; no model output sets an entity (promise 2).

Only claims whose reader could not link the mention (`unresolved`, with a mention and a mention
key) are scored. Per candidate entity the features are:

- `exact_id` / `alias_hit`: the normalised mention equals the canonical name / an alias (1.0);
- `fuzzy`: best `difflib` ratio against the names (string feature);
- `serial`: the mention is a serial (`SN-nnnn`) equal to the candidate's serial alias (non-string);
- `doc_context`: the same document already links another mention to this entity (non-string);
- `digit_transposition`: same digits in another order, e.g. "Press 21" vs "M-12". Named so the
  card can show it; it vetoes the candidate (fail closed). A serial that names a different serial
  of the candidate vetoes it too.

String score = max of the string features (the ConfigBundle carries no feature weights; adding
them is a contract change). Auto-link needs ALL of: top score >= tau_link, top - second >=
delta_link, no veto, and at least one non-string feature. Otherwise the claim becomes
`ambiguous` (or stays `unresolved` when nothing scores) and a review item lists the top 3.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from trace_core.canonical import canonical_sha256
from trace_core.ids import build_claim, review_id
from trace_core.models.claims import Candidate, ClaimRecord, LinkStatus, MentionKey, Subject
from trace_core.models.config import AliasEntry, ConfigBundle
from trace_core.models.records import ReviewItem

TOP_N = 3
_SERIAL = re.compile(r"^sn-?(\d+)$")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _serial(text: str) -> str | None:
    match = _SERIAL.match(re.sub(r"\s+", "", text.casefold()))
    return match.group(1) if match else None


def score_candidate(mention: str, entry: AliasEntry, context_entities: frozenset[str]) -> Candidate:
    names = [entry.canonical_name, *entry.aliases]
    m = _norm(mention)
    features: dict[str, float] = {}
    reasons: list[str] = []
    vetoed = False
    if m == _norm(entry.canonical_name):
        features["exact_id"] = 1.0
        reasons.append("matches the canonical name")
    elif m in {_norm(a) for a in entry.aliases}:
        features["alias_hit"] = 1.0
        reasons.append("matches a registered alias")
    features["fuzzy"] = round(max(SequenceMatcher(None, m, _norm(n)).ratio() for n in names), 6)
    serial = _serial(mention)
    entry_serials = {s for s in (_serial(a) for a in names) if s is not None}
    if serial is not None and entry_serials:
        if serial in entry_serials:
            features["serial"] = 1.0
            reasons.append("serial number matches")
        else:
            vetoed = True
            reasons.append("serial conflict: a different serial number vetoes this machine")
    mention_digits = _digits(mention)
    for name in names:
        theirs = _digits(name)
        if (
            len(mention_digits) > 1
            and mention_digits != theirs
            and sorted(mention_digits) == sorted(theirs)
        ):
            features["digit_transposition"] = 1.0
            reasons.append(f"digit_transposition: {mention_digits} vs {theirs}")
            vetoed = True
    if entry.entity_id in context_entities:
        features["doc_context"] = 1.0
        reasons.append("the same document links another mention to this machine")
    string_score = max(
        features.get("exact_id", 0.0), features.get("alias_hit", 0.0), features["fuzzy"]
    )
    return Candidate(
        entity_id=entry.entity_id,
        score=string_score,
        features=features,
        reasons=reasons,
        vetoed=vetoed,
    )


def _autolink(ranked: Sequence[Candidate], cfg: ConfigBundle) -> Candidate | None:
    if not ranked:
        return None
    top = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    non_string = top.features.get("serial", 0.0) > 0 or top.features.get("doc_context", 0.0) > 0
    if (
        not top.vetoed
        and top.score >= cfg.gate.tau_link
        and top.score - second >= cfg.gate.delta_link
        and non_string
    ):
        return top
    return None


def _rebuild(claim: ClaimRecord, subject: Subject) -> ClaimRecord:
    fields = claim.model_dump(mode="python")
    fields["subject"] = subject
    return build_claim(**fields)


def resolve_entities(
    claims: list[ClaimRecord], cfg: ConfigBundle, *, opened_at: str
) -> tuple[list[ClaimRecord], list[ReviewItem]]:
    context: dict[str, set[str]] = {}
    for claim in claims:
        key = claim.subject.mention_key
        if claim.subject.link_status == "resolved" and claim.subject.entity_id and key:
            context.setdefault(key.source_sha256, set()).add(claim.subject.entity_id)

    out: list[ClaimRecord] = []
    by_key: dict[str, tuple[MentionKey, list[Candidate], list[str]]] = {}
    for claim in claims:
        subject = claim.subject
        mention_key = subject.mention_key
        if subject.link_status != "unresolved" or subject.mention is None or mention_key is None:
            out.append(claim)
            continue
        key = mention_key
        ctx = frozenset(context.get(key.source_sha256, set()))
        ranked = sorted(
            (score_candidate(subject.mention, e, ctx) for e in cfg.aliases),
            key=lambda c: (-c.score, c.entity_id),
        )
        ranked = [c for c in ranked if c.score > 0.0][:TOP_N]
        winner = _autolink(ranked, cfg)
        if winner is not None:
            new = Subject(
                mention=subject.mention,
                entity_id=winner.entity_id,
                link_status="resolved",
                candidates=ranked,
                mention_key=key,
            )
            out.append(_rebuild(claim, new))
            continue
        status: LinkStatus = "ambiguous" if ranked else "unresolved"
        rebuilt = _rebuild(
            claim,
            Subject(
                mention=subject.mention,
                entity_id=None,
                link_status=status,
                candidates=ranked,
                mention_key=key,
            ),
        )
        out.append(rebuilt)
        if ranked:
            slot = by_key.setdefault(key.locator + key.source_sha256, (key, ranked, []))
            slot[2].append(rebuilt.claim_id)

    items = [
        ReviewItem(
            review_id=review_id("ambiguous_entity", [key]),
            type="ambiguous_entity",
            claim_ids=sorted(ids),
            mention_keys=[key],
            candidates=ranked,
            evidence_hash=canonical_sha256({"mention_key": key, "candidates": ranked}),
            opened_at=opened_at,
        )
        for key, ranked, ids in (by_key[k] for k in sorted(by_key))
    ]
    return out, items
