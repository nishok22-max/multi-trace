"""Pure decision/event rules shared by every ClaimStore (and later the decision service)."""

from __future__ import annotations

from typing import assert_never

from trace_core.models.records import Choice, ReviewKind


def event_kind_for(choice: Choice) -> ReviewKind:
    """Which review event a decision produces. `escalated` is derived, never stored, so a
    manual escalation is recorded as `decided` with an escalate decision."""
    match choice.type:
        case "entity" | "reading" | "escalate":
            return "decided"
        case "explain":
            return "explained"
        case _ as unreachable:
            assert_never(unreachable)


def closes_item(choice: Choice) -> bool:
    """True when a second such decision on the same item is `already-decided` (409).
    Escalation never closes an item."""
    return choice.type != "escalate"
