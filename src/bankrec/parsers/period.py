"""Time-period parsing ("first 3 months", "15 billing cycles", "90 days")."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "eighteen": 18,
    "twenty-one": 21,
    "twenty": 20,
    "thirty": 30,
    "sixty": 60,
    "ninety": 90,
}
_NUM = r"(\d{1,3}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_PERIOD = re.compile(
    _NUM + r"[\s-]*(billing\s+cycles?|statement\s+cycles?|days?|months?|years?|weeks?)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Period:
    value: int
    unit: str  # days | weeks | months | years | billing_cycles
    raw: str
    start: int
    end: int

    # Time units are never converted (spot-check round 2, finding C): "3 months" is not 90 days and "15 billing
    # cycles" is not 15 months. ``days`` / ``months`` are set only when the page states that unit.
    @property
    def days(self) -> int | None:
        return self.value if self.unit == "days" else None

    @property
    def months(self) -> int | None:
        return self.value if self.unit == "months" else None


def _num(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token.lower()]


def parse_period(text: str | None) -> Period | None:
    if not text:
        return None
    m = _PERIOD.search(text)
    if not m:
        return None
    unit_raw = m.group(2).lower()
    unit = (
        "billing_cycles"
        if "cycle" in unit_raw
        else "days"
        if unit_raw.startswith("day")
        else "weeks"
        if unit_raw.startswith("week")
        else "months"
        if unit_raw.startswith("month")
        else "years"
    )
    value = _num(m.group(1))
    if value <= 0:
        return None
    return Period(value, unit, m.group(0), m.start(), m.end())
