"""Unit normalisation (B-05, PRD 10.5, promise 5): units are never guessed.

- `sensor_native` claims (MS telemetry) are never converted.
- A `known` unit is converted only through the documented table below, into the attribute's
  documented `canonical_unit`. No documented conversion (or no canonical unit) leaves the claim
  untouched, so the gate later says "can't be compared" instead of guessing.
- `unknown` units stay unknown.
Arithmetic is exact `Decimal`; the stored result is rounded to 6 dp (canonical.py's precision).
"""

from __future__ import annotations

from decimal import Decimal

from trace_core.ids import build_claim
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle

_SIX_DP = Decimal("0.000001")
_PI = Decimal("3.14159265358979323846")

# (from_unit, to_unit) -> (factor, offset): to = from * factor + offset. Physical constants only.
CONVERSIONS: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("bar", "kPa"): (Decimal(100), Decimal(0)),
    ("MPa", "kPa"): (Decimal(1000), Decimal(0)),
    ("Pa", "kPa"): (Decimal("0.001"), Decimal(0)),
    ("psi", "kPa"): (Decimal("6.894757293168"), Decimal(0)),
    ("degF", "degC"): (Decimal(5) / Decimal(9), Decimal(-160) / Decimal(9)),
    ("K", "degC"): (Decimal(1), Decimal("-273.15")),
    ("rad/s", "rpm"): (Decimal(60) / (Decimal(2) * _PI), Decimal(0)),
}


def convert(value: Decimal, unit: str, target: str, *, quantize: bool = True) -> Decimal | None:
    """The documented conversion in either direction of a documented pair, or None when there is
    none (never a guess). `quantize=False` keeps full precision (round-trip checks)."""
    if unit == target:
        return value
    rule = CONVERSIONS.get((unit, target))
    if rule is not None:
        factor, offset = rule
        out = value * factor + offset
    else:
        inverse = CONVERSIONS.get((target, unit))
        if inverse is None:
            return None
        factor, offset = inverse
        out = (value - offset) / factor
    return out.quantize(_SIX_DP) if quantize else out


def _normalised(claim: ClaimRecord, canonical: dict[str, str | None]) -> ClaimRecord:
    if (
        claim.unit_status != "known"
        or claim.unit is None
        or claim.value_type != "numeric"
        or isinstance(claim.value, bool)
        or not isinstance(claim.value, int | float)
    ):
        return claim
    target = canonical.get(claim.attribute)
    if target is None:
        return claim
    converted = convert(Decimal(str(claim.value)), claim.unit, target)
    if converted is None:
        return claim  # undocumented conversion: left alone, the gate reports it
    fields = claim.model_dump(mode="python")
    fields.update(normalized_value=float(converted), normalized_unit=target)
    return build_claim(**fields)


def normalise_units(claims: list[ClaimRecord], cfg: ConfigBundle) -> list[ClaimRecord]:
    canonical = {a.name: a.canonical_unit for a in cfg.ontology.attributes}
    return [_normalised(c, canonical) for c in claims]
