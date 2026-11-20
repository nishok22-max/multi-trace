"""Hypothesis properties for canonical.py and ids.py (promise 8, determinism)."""

from __future__ import annotations

import json
import random
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.factories import claim_fields
from trace_core.canonical import canonical_bytes, canonical_sha256, quantize6
from trace_core.errors import CanonicalizationError
from trace_core.ids import build_claim

finite = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e12, max_value=1e12)
scalars = st.none() | st.booleans() | st.integers(-(2**50), 2**50) | finite | st.text(max_size=12)
json_values = st.recursive(
    scalars,
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4)
    ),
    max_leaves=12,
)


@given(json_values)
def test_canonical_round_trip(value: Any) -> None:
    once = canonical_bytes(value)
    assert canonical_bytes(json.loads(once)) == once  # idempotent through JSON


@given(finite)
def test_six_dp_quantisation_half_even(x: float) -> None:
    expected = format(Decimal(repr(x)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")
    got = quantize6(x)
    if Decimal(expected) == 0:
        expected = "0.000000"
    assert got == expected
    assert canonical_bytes(x) == canonical_bytes(float(got))  # re-quantising changes nothing


def test_half_even_ties() -> None:
    assert quantize6(0.0000025) == "0.000002"  # tie -> even
    assert quantize6(0.0000035) == "0.000004"
    assert quantize6(2.5e-7) == "0.000000"


@given(st.floats(min_value=-4e-7, max_value=0.0, allow_nan=False))
def test_negative_zero_equals_zero(x: float) -> None:
    assert canonical_bytes(x) == canonical_bytes(0.0)
    assert canonical_bytes(-0.0) == canonical_bytes(0.0) == canonical_bytes(Decimal("-0"))
    assert quantize6(x) == "0.000000"


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("Infinity")]
)
def test_nan_and_inf_rejected(bad: object) -> None:
    for wrapped in (bad, [bad], {"a": bad}, {"a": [{"b": bad}]}):
        with pytest.raises(CanonicalizationError):
            canonical_bytes(wrapped)


@given(
    st.dictionaries(st.text(min_size=1, max_size=5), scalars, min_size=2, max_size=6),
    st.randoms(use_true_random=False),
)
def test_dict_key_order_does_not_change_the_hash(d: dict[str, Any], rnd: random.Random) -> None:
    items = list(d.items())
    rnd.shuffle(items)
    assert canonical_sha256(dict(items)) == canonical_sha256(d)


@given(
    st.lists(
        st.sampled_from([f"clm_{c * 24}" for c in "abcdef"]), min_size=2, max_size=6, unique=True
    ),
    st.randoms(use_true_random=False),
)
def test_ids_content_addressed_order_independent(parents: list[str], rnd: random.Random) -> None:
    """prop_ids_content_addressed: derived_from order never changes the claim id."""
    shuffled = list(parents)
    rnd.shuffle(shuffled)
    over = {
        "claim_type": "inferred",
        "evidence": None,
        "method": {"extractor": "e", "extractor_version": "1", "rule_id": "r"},
    }
    a = build_claim(**claim_fields(0, derived_from=parents, **over))
    b = build_claim(**claim_fields(0, derived_from=shuffled, **over))
    assert a.claim_id == b.claim_id and a.record_hash != "" and len(a.claim_id) == 28
