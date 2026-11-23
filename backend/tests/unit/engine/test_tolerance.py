"""B-08: numeric vs numeric tolerance (PRD 10.5). Tolerances come from the config (datasheets);
none is invented, so without one nothing is judged."""

from __future__ import annotations

import pytest

from tests.unit.engine.test_gaps import CFG
from tests.unit.engine.test_units import _gauge
from trace_core.compare.gate import gate
from trace_core.ids import config_hash
from trace_core.models.claims import ClaimRecord
from trace_core.models.config import ConfigBundle, Tolerance
from trace_core.normalise.units import normalise_units
from trace_core.stage_types import GateContext


def _ctx(*tolerances: Tolerance) -> GateContext:
    config: ConfigBundle = CFG.model_copy(update={"tolerances": list(tolerances)})
    return GateContext(config=config, config_hash=config_hash(config), envelopes=[])


def _kpa(value: float, unit: str = "bar") -> ClaimRecord:
    (claim,) = normalise_units([_gauge(value, unit)], CFG)
    return claim


TOL = Tolerance(attribute="pressure", abs_tol=2.0, rel_tol=0.01, resolution=0.0)


def test_agree_within_the_larger_of_abs_and_relative_tolerance() -> None:
    a, b = _kpa(2.5), _kpa(2.51)  # 250.0 kPa vs 251.0 kPa: gap 1.0 <= max(2.0, 2.5)
    record = gate(a, b, _ctx(TOL))
    assert record.outcome == "agree" and [c.n for c in record.checks] == [1, 2, 3, 4, 5, 6]
    assert gate(b, a, _ctx(TOL)).outcome == "agree"


def test_disagree_beyond_tolerance_and_values_are_never_averaged() -> None:
    a, b = _kpa(2.5), _kpa(3.0)  # 250 kPa vs 300 kPa
    record = gate(a, b, _ctx(TOL))
    assert record.outcome == "disagree" and "differ beyond tolerance" in record.reason
    assert "average" not in record.reason.lower() and "mean" not in record.reason.lower()


def test_measurement_resolution_widens_the_limit() -> None:
    a, b = _kpa(2.5), _kpa(2.6)  # gap 10 kPa
    tight = Tolerance(attribute="pressure", abs_tol=0.0, rel_tol=0.0, resolution=1.0)
    assert gate(a, b, _ctx(tight)).outcome == "disagree"  # 2 * 1 = 2 < 10
    coarse = Tolerance(attribute="pressure", abs_tol=0.0, rel_tol=0.0, resolution=5.0)
    assert gate(a, b, _ctx(coarse)).outcome == "agree"  # 2 * 5 = 10 >= 10


def test_a_documented_conversion_makes_different_units_comparable() -> None:
    bar, psi = _kpa(2.0, "bar"), _kpa(29.0075, "psi")  # both ~200 kPa
    assert gate(bar, psi, _ctx(TOL)).outcome == "agree"


def test_no_tolerance_or_undocumented_unit_is_cant_compare() -> None:
    a, b = _kpa(2.5), _kpa(2.5)
    assert gate(a, b, _ctx()).outcome == "cant_compare"  # no datasheet value: nothing invented
    odd = _gauge(2.5, "furlongs")  # no documented conversion: stays in its own unit
    record = gate(a, odd, _ctx(TOL))
    assert record.outcome == "cant_compare" and not record.checks[-1].passed
    assert "units differ" in record.checks[-1].detail


def test_other_attributes_are_not_compared() -> None:
    a = _kpa(2.5)
    temp = _gauge(2.5, "bar").model_copy(update={"attribute": "temperature"})
    assert gate(a, temp, _ctx(TOL)).outcome == "cant_compare"
    with pytest.raises(AssertionError):
        assert gate(a, a, _ctx(TOL)).outcome == "disagree"
