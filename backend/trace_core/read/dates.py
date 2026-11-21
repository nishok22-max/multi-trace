"""Thin, deterministic date reader for labelled document dates (M2).

Only `Label: DD Mon YYYY [HH:MM]` is understood, with English month names. There is no
dateparser, no relative base and no guessing: anything else yields None, so the claim gets
`UnknownTime` (PRD 10.2). The full rules (relative dates, shifts) arrive in M3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}


@dataclass(frozen=True)
class LabelledDate:
    day: date
    at: time | None


def find_labelled_date(text: str, label: str) -> LabelledDate | None:
    pattern = (
        rf"{re.escape(label)}\s*:\s*(\d{{1,2}})\s+([A-Za-z]{{3,9}})\s+(\d{{4}})"
        r"(?:\s+(\d{1,2}):(\d{2}))?"
    )
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None
    try:
        day = date(int(match.group(3)), month, int(match.group(1)))
        at = time(int(match.group(4)), int(match.group(5))) if match.group(4) else None
    except ValueError:
        return None
    return LabelledDate(day=day, at=at)
