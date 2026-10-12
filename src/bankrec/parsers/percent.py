"""Percentage and APR/APY parsing. Values are Decimal percentages (4.25 means 4.25%)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from bankrec.parsers.placeholders import contains_placeholder, is_placeholder

_PCT = r"(\d{1,2}(?:\.\d{1,3})?)\s*%"
_RANGE = re.compile(_PCT + r"\s*(?:-|–|—|to|through)\s*" + _PCT, re.IGNORECASE)
_SINGLE = re.compile(_PCT)
_PRIME = re.compile(r"prime\s*(?:rate)?\s*\+", re.IGNORECASE)


@dataclass(frozen=True)
class PercentRange:
    low: Decimal
    high: Decimal
    variable: bool
    start: int
    end: int


def parse_percent(text: str | None) -> Decimal | None:
    """Single percentage. "4.25% APY" -> Decimal("4.25"); "NaN%" -> None."""
    if text is None or is_placeholder(text) or contains_placeholder(text):
        return None
    m = _SINGLE.search(text)
    return Decimal(m.group(1)) if m else None


def parse_percent_range(text: str | None) -> PercentRange | None:
    """APR range. "20.24% - 29.24% Variable" -> (20.24, 29.24, variable=True).

    A single value yields low == high. Prime-plus margins ("Prime + 12.99%") are ambiguous and return None
    rather than a computed guess.
    """
    if text is None or is_placeholder(text) or contains_placeholder(text):
        return None
    if _PRIME.search(text):
        return None
    variable = bool(re.search(r"\bvariable\b", text, re.IGNORECASE))
    m = _RANGE.search(text)
    if m:
        lo, hi = Decimal(m.group(1)), Decimal(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return PercentRange(lo, hi, variable, m.start(), m.end())
    m1 = _SINGLE.search(text)
    if m1:
        v = Decimal(m1.group(1))
        return PercentRange(v, v, variable, m1.start(), m1.end())
    return None
