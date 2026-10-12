"""Reward-rate parsing for credit cards.

Input is one reward statement (a bullet or sentence). Output is a structured rate with caps, post-cap rate,
rotating/activation/portal flags and an optional end date. The caller keeps the statement's span as provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from bankrec.normalize.categories import categories_in
from bankrec.parsers.money import _dollars_to_cents
from bankrec.parsers.placeholders import contains_placeholder

_RATE = re.compile(
    r"(?P<num>\d{1,2}(?:\.\d{1,2})?)\s*(?:(?P<pct>%)\s*(?:cash\s*back|back|cash\s*rewards?)?|"
    r"\s*(?P<x>[xX])\b(?:\s*(?:membership\s+rewards®?\s+)?(?:points|miles))?|"
    r"\s+(?P<per>points|miles)\s+per\s+(?:\$1|dollar))",
)
_CAP = re.compile(
    r"(?:on\s+)?up\s+to\s+\$\s*(?P<amt>[\d,]+(?:\.\d{1,2})?)\s+(?:in\s+)?(?P<combined>combined\s+)?(?:eligible\s+)?"
    r"(?:purchases|spend(?:ing)?)?[^.;()]*?(?:per|each|a|every)\s+(?P<period>calendar\s+year|year|quarter|month|"
    r"billing\s+cycle|cardmember\s+year)",
    re.IGNORECASE,
)
_POST_CAP = re.compile(
    r"(?:then|after that,?)\s+(?P<num>\d{1,2}(?:\.\d{1,2})?)\s*(?:%|[xX]\b)", re.IGNORECASE
)
_ROTATING = re.compile(
    r"\b(?:rotating|bonus categories (?:that change )?each quarter|quarterly bonus categories|"
    r"categories each quarter)\b",
    re.IGNORECASE,
)
_ACTIVATION = re.compile(r"\b(?:activate|activation|enroll(?:ment)?|opt[- ]in)\b", re.IGNORECASE)
_PORTAL = re.compile(
    r"\b(?:booked|purchased|reserved|made)\s+(?:directly\s+)?(?:through|via|on)\s+(?:the\s+)?"
    r"(?:chase travel|capital one travel|amex ?travel|american express travel|ultimate rewards|"
    r"(?:[A-Z][\w.]+\s+){0,3}(?:travel\s+)?(?:portal|center|centre))|\btravel portal\b",
    re.IGNORECASE,
)
_UNTIL = re.compile(
    r"\b(?:through|until|thru|ending)\s+(?P<m>january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
_PERIODS = {
    "calendar year": "annual",
    "year": "annual",
    "cardmember year": "annual",
    "quarter": "quarterly",
    "month": "monthly",
    "billing cycle": "monthly",
}


@dataclass
class RewardRate:
    rate: Decimal
    rate_unit: str  # "pct" (cash back %) or "x" (points/miles per dollar)
    categories: list[str]
    cap_cents: int | None = None
    cap_period: str | None = None
    cap_combined: bool = False
    post_cap_rate: Decimal | None = None
    is_rotating: bool = False
    requires_activation: bool = False
    portal_only: bool = False
    ends_on: date | None = None
    is_base: bool = False
    text: str = ""
    notes: list[str] = field(default_factory=list)


def parse_reward_statement(text: str) -> RewardRate | None:
    """Parse one earn-rate statement. Returns None when no rate is present or the text holds a placeholder."""
    if contains_placeholder(text):
        return None
    m = _RATE.search(text)
    if not m:
        return None
    rate = Decimal(m.group("num"))
    unit = "pct" if m.group("pct") else "x"
    rest = text[m.end() :]
    cats = categories_in(rest) or categories_in(text)
    is_base = "other" in cats and len(cats) == 1
    cats = [c for c in cats if c != "other"] or (["other"] if is_base else [])
    rr = RewardRate(rate=rate, rate_unit=unit, categories=cats, is_base=is_base, text=text.strip())
    cap = _CAP.search(text)
    if cap:
        rr.cap_cents = _dollars_to_cents(cap.group("amt"))
        rr.cap_period = _PERIODS[re.sub(r"\s+", " ", cap.group("period").lower())]
        rr.cap_combined = bool(cap.group("combined"))
        post = _POST_CAP.search(text, cap.end() - 1) or _POST_CAP.search(text)
        if post:
            rr.post_cap_rate = Decimal(post.group("num"))
        else:
            rr.notes.append("cap without stated post-cap rate; base rate applies")
    rr.is_rotating = bool(_ROTATING.search(text)) or "rotating" in cats
    if rr.is_rotating:
        rr.categories = ["rotating"]
    rr.requires_activation = bool(_ACTIVATION.search(text))
    rr.portal_only = bool(_PORTAL.search(text))
    until = _UNTIL.search(text)
    if until:
        rr.ends_on = date(int(until.group("y")), _MONTHS[until.group("m").lower()], int(until.group("d")))
    if not rr.categories:
        return None
    return rr
