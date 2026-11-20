"""Canonical JSON for hashing: RFC 8785 (JCS) with deterministic number handling.

Rules (IMPLEMENTATION_PLAN A.3, SYSTEM_DESIGN 9):
- floats and Decimals become fixed 6-decimal strings, quantised ROUND_HALF_EVEN;
- -0.0 becomes 0; NaN and Inf are rejected;
- sets are sorted; dict keys must be strings (JCS sorts them, so key order never matters);
- wall-clock fields (declared per model in `wall_clock_fields`) are excluded from record hashes.

The float -> Decimal step uses `repr(float)` (shortest round-trip decimal), so the rounding
is decided on the decimal the author wrote, not on the binary expansion.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

import rfc8785
from pydantic import BaseModel

from trace_core.errors import CanonicalizationError
from trace_core.models.base import CoreModel, WireModel

CANON_VERSION = "1"
_QUANT = Decimal("0.000001")


def quantize6(value: float | Decimal) -> str:
    """Fixed 6-dp string, half-even, never '-0.000000'."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalizationError("NaN/Inf cannot be canonicalised")
        dec = Decimal(repr(value))
    else:
        if not value.is_finite():
            raise CanonicalizationError("NaN/Inf cannot be canonicalised")
        dec = value
    q = dec.quantize(_QUANT, rounding=ROUND_HALF_EVEN)
    if q == 0:
        q = Decimal(0).quantize(_QUANT)
    return format(q, "f")


def _canon(obj: Any) -> Any:
    if obj is None or isinstance(obj, bool | str):
        return obj
    if isinstance(obj, Enum):
        return _canon(obj.value)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float | Decimal):
        return quantize6(obj)
    if isinstance(obj, CoreModel | WireModel):
        return _canon(dump_body(obj))
    if isinstance(obj, BaseModel):
        raise CanonicalizationError(f"unsupported model {type(obj).__name__}")
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, val in obj.items():
            if not isinstance(key, str):
                raise CanonicalizationError("dict keys must be strings")
            out[key] = _canon(val)
        return out
    if isinstance(obj, list | tuple):
        return [_canon(v) for v in obj]
    if isinstance(obj, set | frozenset):
        return sorted(_canon(v) for v in obj)
    raise CanonicalizationError(f"unsupported type {type(obj).__name__}")


def dump_body(model: CoreModel | WireModel, *, drop_wall_clock: bool = True) -> dict[str, Any]:
    """Recursive dump by field name, dropping each model's own wall-clock fields."""
    skip = type(model).wall_clock_fields if drop_wall_clock else frozenset()
    body: dict[str, Any] = {}
    for name, info in type(model).model_fields.items():
        if name in skip:
            continue
        body[info.alias or name] = _dump_value(getattr(model, name), drop_wall_clock)
    return body


def _dump_value(value: Any, drop_wall_clock: bool) -> Any:
    if isinstance(value, CoreModel | WireModel):
        return dump_body(value, drop_wall_clock=drop_wall_clock)
    if isinstance(value, list | tuple):
        return [_dump_value(v, drop_wall_clock) for v in value]
    if isinstance(value, dict):
        return {k: _dump_value(v, drop_wall_clock) for k, v in value.items()}
    return value


def canonical_bytes(obj: Any) -> bytes:
    """JCS bytes of `obj` after number/set normalisation."""
    return rfc8785.dumps(_canon(obj))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(obj: Any) -> str:
    return sha256_hex(canonical_bytes(obj))


def record_hash(model: CoreModel | WireModel, *, exclude: frozenset[str] = frozenset()) -> str:
    """sha256(JCS(body minus wall-clock fields)), optionally minus extra named top-level fields."""
    body = {k: v for k, v in dump_body(model).items() if k not in exclude}
    return canonical_sha256(body)
