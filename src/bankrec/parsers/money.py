"""Money parsing. All amounts are integer cents. Never guesses: text without a number yields None
unless it is an explicit zero phrase."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bankrec.parsers.placeholders import is_placeholder

_ZERO_PHRASES = re.compile(
    r"\b(?:no annual fee|no monthly (?:maintenance |service )?fee|\$0(?:\.00)?(?!\d)|no foreign transaction fees?|"
    r"no fee|none)\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?!\d)(\s*(?:k|thousand)\b)?", re.IGNORECASE
)
_MARKETING = re.compile(
    r"\b(?:more than|over|worth|value of)\s+\$[\d,]+(?:\.\d+)?\s+(?:in|of)\s+(?:annual\s+)?value",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Money:
    cents: int
    start: int
    end: int


def _to_cents(whole: str, frac: str | None, thousand: str | None) -> int:
    cents = int(whole.replace(",", "")) * 100 + (int(frac.ljust(2, "0")) if frac else 0)
    if thousand:
        cents *= 1000
    return cents


def _dollars_to_cents(token: str) -> int:
    whole, _, frac = token.partition(".")
    return _to_cents(whole, frac or None, None)


def find_amounts(text: str) -> list[Money]:
    """All dollar amounts in ``text`` with their spans. Marketing aggregates are excluded (brief §7.3)."""
    excluded = [(m.start(), m.end()) for m in _MARKETING.finditer(text)]
    out: list[Money] = []
    for m in _AMOUNT.finditer(text):
        if any(s <= m.start() < e for s, e in excluded):
            continue
        out.append(Money(_to_cents(m.group(1), m.group(2), m.group(3)), m.start(), m.end()))
    return out


def parse_money(text: str | None) -> int | None:
    """Parse a single fee/amount field into cents.

    "$95" -> 9500; "$1,250.50" -> 125050; "No annual fee" -> 0; "$" / "NaN" / "" -> None.
    If several amounts are present the first is returned; callers that need intro/ongoing splits use
    :func:`parse_fee_schedule`.
    """
    if text is None or is_placeholder(text):
        return None
    amounts = find_amounts(text)
    if amounts:
        return amounts[0].cents
    if _ZERO_PHRASES.search(text):
        return 0
    return None


@dataclass(frozen=True)
class FeeSchedule:
    ongoing_cents: int | None
    intro_cents: int | None = None
    intro_text: str | None = None


_INTRO_THEN = re.compile(
    r"\$\s*(?P<intro>[\d,]+(?:\.\d{1,2})?)\s*(?:intro(?:ductory)?\s*(?:annual fee\s*)?)?(?P<period>for the first year|"
    r"(?:for\s+)?(?:the\s+)?first\s+(?:\d+|one|two)\s+years?|intro(?:ductory)? annual fee for the first year)"
    r"[^$]{0,40}?then\s+\$\s*(?P<then>[\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def parse_fee_schedule(text: str | None) -> FeeSchedule:
    """Split "$0 intro annual fee for the first year, then $95" into intro and ongoing parts."""
    if text is None or is_placeholder(text):
        return FeeSchedule(None)
    m = _INTRO_THEN.search(text)
    if m:
        return FeeSchedule(
            ongoing_cents=_dollars_to_cents(m.group("then")),
            intro_cents=_dollars_to_cents(m.group("intro")),
            intro_text=m.group("period"),
        )
    return FeeSchedule(parse_money(text))
