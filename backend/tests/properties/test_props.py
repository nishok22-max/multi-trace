"""B-11: the remaining Hypothesis properties (TEST_PLAN 4). Named: prop_unit_roundtrip,
prop_overlap_commutative, prop_half_open_days_partition, prop_chain_detects_any_edit,
prop_ids_content_addressed, prop_conformal_bound, prop_quote_offset_map,
prop_explain_never_changes_outcome, prop_status_derived_monotone, prop_hidden_char_holds_span,
prop_held_never_pairs."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from reportlab.pdfgen.canvas import Canvas

from tests.factories import decision_event, make_decision, make_review_item, opened_event, sha
from tests.skeleton.world import World, build_version, synthetic_world
from tests.unit.engine.test_entities import _claim as entity_claim
from tests.unit.engine.test_gaps import CFG
from tests.unit.engine.test_hidden_text import LINE, _read
from tests.unit.engine.test_trust import _resolved
from tests.unit.engine.test_units import _gauge
from trace_adapters.fakes.clock import FixedClock
from trace_core.compare.pairs import candidate_pairs
from trace_core.ids import build_claim, claim_id, review_id
from trace_core.models.case import CaseVersion
from trace_core.models.claims import Candidate, Subject
from trace_core.models.config import WorkingCalendar
from trace_core.models.records import ExplainChoice, ReadingChoice, ReviewItem
from trace_core.models.time import Interval, UnknownTime
from trace_core.normalise.envelopes import conformal_rank
from trace_core.normalise.time import local_date, local_day_bounds, overlaps, parse_utc
from trace_core.normalise.units import CONVERSIONS, convert, normalise_units
from trace_core.read.text import read_plaintext
from trace_core.rerun import rerun_after_decision
from trace_core.review.holds import apply_holds
from trace_core.review.status import add_working_days, derive_review_status
from trace_core.score.confidence import score, score_pre
from trace_core.snapshot.integrity import verify_chain
from trace_core.stage_types import Provenance

PROFILE = settings(
    deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)


# ------------------------------------------------------------------------------ units
PAIRS = sorted(CONVERSIONS)


@PROFILE
@given(
    pair=st.sampled_from(PAIRS),
    x=st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=6),
)
def test_prop_unit_roundtrip(pair: tuple[str, str], x: Decimal) -> None:
    u, v = pair
    there = convert(x, u, v, quantize=False)
    assert there is not None
    back = convert(there, v, u, quantize=False)
    assert back is not None
    assert abs(back - x) <= Decimal("1e-9") * max(Decimal(1), abs(x))
    assert convert(x, u, u) == x  # same unit: identity


def test_prop_unit_roundtrip_no_normalised_value_for_unknown_or_native() -> None:
    for status in ("unknown", "sensor_native"):
        claim = _gauge(2.5, "bar", status)
        out = normalise_units([claim], CFG)[0]
        assert out.normalized_value is None and out.normalized_unit is None


# ------------------------------------------------------------------------------ time
def _interval(start: int, length: int) -> Interval:
    base = datetime(2015, 1, 1, tzinfo=UTC)
    s, e = base + timedelta(hours=start), base + timedelta(hours=start + length)
    return Interval(
        start=s.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end=e.strftime("%Y-%m-%dT%H:%M:%SZ"),
        granularity="hour",
        resolved_from="explicit",
    )


@given(a=st.integers(0, 500), la=st.integers(1, 100), b=st.integers(0, 500), lb=st.integers(1, 100))
def test_prop_overlap_commutative(a: int, la: int, b: int, lb: int) -> None:
    i, j = _interval(a, la), _interval(b, lb)
    assert overlaps(i, j) == overlaps(j, i)
    assert overlaps(i, i)
    meets = _interval(a + la, lb)
    assert not overlaps(i, meets) and not overlaps(meets, i)  # [a,b) and [b,c) never overlap
    unknown = UnknownTime(reason="no date")
    assert not overlaps(i, unknown) and not overlaps(unknown, i) and not overlaps(unknown, unknown)


ZONES = ("Asia/Kolkata", "Europe/Berlin", "America/New_York", "UTC")


@PROFILE
@given(
    zone=st.sampled_from(ZONES),
    minutes=st.integers(min_value=0, max_value=60 * 24 * 365 * 4),
)
def test_prop_half_open_days_partition(zone: str, minutes: int) -> None:
    """Exactly one plant-local day [D 00:00, D+1 00:00) contains any instant; days are contiguous
    across DST changes."""
    t = datetime(2014, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes)
    instant = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    day = local_date(instant, zone)
    containing = [
        d
        for d in (day - timedelta(days=1), day, day + timedelta(days=1))
        if local_day_bounds(d, zone)[0] <= instant < local_day_bounds(d, zone)[1]
    ]
    assert containing == [day]
    assert local_day_bounds(day, zone)[1] == local_day_bounds(day + timedelta(days=1), zone)[0]
    assert parse_utc(local_day_bounds(day, zone)[0]) < parse_utc(local_day_bounds(day, zone)[1])


# ------------------------------------------------------------------------------ chain, ids
@pytest.fixture(scope="module")
def world_chain(tmp_path_factory: pytest.TempPathFactory) -> tuple[World, CaseVersion, CaseVersion]:
    from trace_adapters.pdfium_reader import PdfiumReader
    from trace_core.build import build_case
    from trace_worker.env import snapshot_hashes

    world = synthetic_world(tmp_path_factory.mktemp("props-chain"), spike=False)
    v1 = build_version(world)
    v2 = build_case(
        world.manifest(),
        CFG,
        [],
        world.ports(),
        parent=v1,
        hashes=snapshot_hashes(CFG, PdfiumReader.binary_version()),
    )
    return world, v1, v2


@PROFILE
@given(data=st.data())
def test_prop_chain_detects_any_edit(
    data: st.DataObject, world_chain: tuple[World, CaseVersion, CaseVersion]
) -> None:
    """Editing, deleting, reordering or inserting a record of v1 fails the chain at v1 and v2."""
    _, v1, v2 = world_chain
    claims = list(v1.records.claims)
    op = data.draw(st.sampled_from(["edit", "delete", "reorder", "insert"]))
    k = data.draw(st.integers(0, len(claims) - 1))
    if op == "edit":
        claims[k] = claims[k].model_copy(update={"statement": claims[k].statement + " (edited)"})
    elif op == "delete":
        del claims[k]
    elif op == "reorder":
        j = data.draw(st.integers(0, len(claims) - 1).filter(lambda x: x != k))
        claims[k], claims[j] = claims[j], claims[k]
    else:
        claims.append(claims[k])  # a duplicated record
    tampered = v1.model_copy(update={"records": v1.records.model_copy(update={"claims": claims})})
    result = verify_chain([tampered, v2])
    assert not result.ok
    assert not result.snapshot_ok or not result.records_ok  # caught at the edited version
    assert verify_chain([v1, v2]).ok  # and the untouched chain stays green


NON_SEMANTIC = st.sampled_from(["statement", "label", "created_at"])


@PROFILE
@given(
    field=st.sampled_from(["statement", "label", "created_at", "value", "attribute"]),
    junk=st.text(min_size=1, max_size=12),
)
def test_prop_ids_content_addressed(field: str, junk: str) -> None:
    base = _resolved(0)
    changed = base.model_copy(
        update={
            "statement": base.statement + junk,
            "label": junk,
            "created_at": "2020-01-01T00:00:00Z",
        }
        if field in ("statement", "label", "created_at")
        else {field: (base.value if field == "attribute" else str(base.value) + junk)}
        if field == "value"
        else {"attribute": base.attribute + junk}
    )
    if field in ("statement", "label", "created_at"):
        assert claim_id(changed) == claim_id(base)  # display text and wall-clock never matter
    else:
        assert claim_id(changed) != claim_id(base)  # any semantic change changes the id
    permuted = [build_claim(**c.model_dump(mode="python")) for c in (base, _resolved(40))]
    assert [c.claim_id for c in reversed(permuted)] == [
        c.claim_id for c in reversed([base, _resolved(40)])
    ]


# --------------------------------------------------------------------------- conformal
@PROFILE
@given(n=st.integers(19, 400))
def test_prop_conformal_rank(n: int) -> None:
    """For n >= 19 and alpha = 0.05 the rank k = ceil(0.95 (n + 1)) always exists (k <= n)."""
    k = conformal_rank(n, 0.05)
    assert k == math.ceil(Fraction(95, 100) * (n + 1))  # exact, no float rounding at the edge
    assert 1 <= k <= n
    assert conformal_rank(18, 0.05) == 19  # n < 19: the rank would not exist: pooling is needed


def test_prop_conformal_bound() -> None:
    """On exchangeable quiet days the false-alarm rate is at most alpha (+ 3 sigma)."""
    rng = np.random.default_rng(20150805)
    n, trials, alpha = 30, 10_000, 0.05
    alarms = 0
    for _ in range(trials):
        days = rng.exponential(1.0, size=n + 1)
        stats, new = np.sort(days[:n]), days[n]
        t_star = stats[conformal_rank(n, alpha) - 1]
        alarms += int(new > t_star)
    sigma = math.sqrt(alpha * (1 - alpha) / trials)
    assert alarms / trials <= alpha + 3 * sigma


# ---------------------------------------------------------------------------- quotes
JUNK = st.text(
    alphabet=st.sampled_from(["a", "b", " ", "\U0001f600", "e", "́", "é", "7", "-"]),
    max_size=20,
)


@PROFILE
@given(before=JUNK, after=JUNK, eol=st.sampled_from(["\n", "\r\n"]), tag=st.integers(0, 9999))
def test_prop_quote_offset_map(before: str, after: str, eol: str, tag: int) -> None:
    """For any text with surrogate pairs, CRLF and NFC variants, the quote equals the slice."""
    from tests.factories import make_source

    sentence = f"Machine 21 ran normally on shift {tag}"
    text = f"{before}{eol}Report date: 06 Aug 2015 09:10{eol}{sentence}.{eol}{after}{eol}"
    result = read_plaintext(make_source(sha256=sha("q")), text.encode("utf-8"), CFG)
    for claim in result.claims:
        ev = claim.evidence
        assert ev is not None and ev.kind == "text_span"  # type: ignore[union-attr]
        assert text[ev.char_start : ev.char_end] == ev.quote  # type: ignore[union-attr]
        assert ev.quote == "ran normally on shift " + str(tag)  # type: ignore[union-attr]


# ------------------------------------------------------------------------------ explain
@pytest.fixture(scope="module")
def parent(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    version = build_version(synthetic_world(tmp_path_factory.mktemp("props-explain"), spike=True))
    text = next(c for c in version.records.claims if c.modality == "text")
    fields = text.model_dump(mode="python")
    from trace_core.models.claims import MentionKey

    key = MentionKey(source_sha256="a" * 64, locator="p1:10-18")
    fields["subject"] = Subject(
        mention="Press 21",
        entity_id=None,
        link_status="ambiguous",
        candidates=[Candidate(entity_id="machine:21", score=0.6)],
        mention_key=key,
    )
    fields["supersedes"] = None
    amb = build_claim(**fields)
    item = ReviewItem(
        review_id=review_id("ambiguous_entity", [key]),
        type="ambiguous_entity",
        claim_ids=[amb.claim_id],
        mention_keys=[key],
        candidates=[Candidate(entity_id="machine:21", score=0.6)],
        evidence_hash="b" * 64,
        opened_at="2015-08-06T04:00:00Z",
    )
    claims = [c for c in version.records.claims if c.claim_id != text.claim_id] + [amb]
    from trace_core.models.case import VersionRecords

    records = VersionRecords(
        claims=claims,
        comparisons=[],
        conflicts=[],
        envelopes=version.records.envelopes,
        review_items=[item],
        decisions=[],
    )
    return version.model_copy(update={"records": records}), item


@PROFILE
@given(explanation=st.one_of(st.none(), st.text(max_size=60)))
def test_prop_explain_never_changes_outcome(explanation: str | None, parent) -> None:  # type: ignore[no-untyped-def]
    base, item = parent
    plain = rerun_after_decision(base, [], CFG, FixedClock("2015-08-06T05:00:00Z"))
    decision = make_decision(item, ExplainChoice(explanation=explanation))
    explained = rerun_after_decision(base, [decision], CFG, FixedClock("2015-08-06T05:00:00Z"))
    assert explained.records.comparisons == plain.records.comparisons
    assert explained.records.conflicts == plain.records.conflicts
    assert [c.claim_id for c in explained.records.claims] == [
        c.claim_id for c in plain.records.claims
    ]


# ------------------------------------------------------------------------------ status
def _oracle_escalated(opened: datetime, now: datetime, cal: WorkingCalendar) -> bool:
    """Independent count: the deadline is N working days after the opening date, same time."""
    day, left = opened.date(), cal.escalation_working_days
    while left:
        day += timedelta(days=1)
        if day.weekday() in cal.working_weekdays and day.isoformat() not in cal.holidays:
            left -= 1
    return now > datetime.combine(day, opened.time(), tzinfo=UTC)


@PROFILE
@given(
    opened_h=st.integers(0, 24 * 40),
    now_h=st.integers(0, 24 * 60),
    decided=st.booleans(),
)
def test_prop_status_derived_monotone(opened_h: int, now_h: int, decided: bool) -> None:
    cal = CFG.case.calendar
    base = datetime(2015, 3, 2, 9, 0, tzinfo=UTC)
    opened, now = base + timedelta(hours=opened_h), base + timedelta(hours=now_h)
    item = make_review_item(["clm_" + "0" * 24]).model_copy(
        update={"opened_at": opened.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )
    events = [opened_event(item)]
    clock = FixedClock(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    before = derive_review_status([item], events, clock, cal)[item.review_id]
    if decided:
        events = [*events, decision_event(make_decision(item, ReadingChoice(verdict="accept")), 1)]
    after = derive_review_status([item], events, clock, cal)[item.review_id]
    assert before == ("escalated" if _oracle_escalated(opened, now, cal) else "open")
    assert after == ("decided" if decided else before)
    # pure: the same inputs always give the same answer, and appending never changes the past
    assert derive_review_status([item], events, clock, cal)[item.review_id] == after
    assert add_working_days(date(2015, 3, 6), 1, cal) == date(2015, 3, 9)  # Friday -> Monday


# ------------------------------------------------------------------------------ hidden
INVISIBLE = ("white", "tiny", "covered")


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cut=st.integers(0, len(LINE) - 2),
    width=st.integers(1, 6),
    how=st.sampled_from(INVISIBLE),
)
def test_prop_hidden_char_holds_span(cut: int, width: int, how: str, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    """Any non-whitespace character made invisible holds the span: 0 claims, 1 review item."""
    end = min(len(LINE), cut + width)
    if not LINE[cut:end].strip():
        return  # whitespace is not a hidden character
    head, mid, tail = LINE[:cut], LINE[cut:end], LINE[end:]

    def draw(c: Canvas) -> None:
        font = "Helvetica"
        c.setFont(font, 14)
        x = 72.0
        c.drawString(x, 700, "Machine 21 " + head)
        x += c.stringWidth("Machine 21 " + head, font, 14)
        if how == "white":
            c.setFillColorRGB(1, 1, 1)
            c.drawString(x, 700, mid)
            c.setFillColorRGB(0, 0, 0)
        elif how == "tiny":
            c.setFont(font, 2)
            c.drawString(x, 700, mid)
            c.setFont(font, 14)
        else:
            c.drawString(x, 700, mid)
            c.setFillColorRGB(0, 0, 0)
            c.rect(x - 1, 696, c.stringWidth(mid, font, 14) + 2, 18, stroke=0, fill=1)
        x += c.stringWidth(mid, font, 14)
        c.drawString(x, 700, tail)

    result = _read(tmp_path_factory.mktemp("hidden"), draw)
    assert result.claims == [] and [i.type for i in result.review_items] == ["hidden_text"]


# ------------------------------------------------------------------------------ held
@PROFILE
@given(held_mask=st.lists(st.booleans(), min_size=2, max_size=6))
def test_prop_held_never_pairs(held_mask: list[bool]) -> None:
    """No comparison pair ever contains a held claim, and `score` never changes the held set."""
    claims = [
        _resolved(i * 40) if not held else entity_claim("Zzzz", "ambiguous", None, i * 40)
        for i, held in enumerate(held_mask)
    ]
    scored = score_pre(claims, CFG)
    eligible, held = apply_holds(scored, [], [], [], CFG)
    held_ids = {c.claim_id for c in held}
    groups = {"operating_state": "operating_state"}
    for a, b in candidate_pairs(eligible, groups):
        assert a.claim_id not in held_ids and b.claim_id not in held_ids
    final = score(scored, [], Provenance(), CFG)
    assert {c.claim_id for c in apply_holds(final, [], [], [], CFG)[1]} == held_ids
