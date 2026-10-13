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
    r"\s+(?P<per>points?|miles?|avios)\s+(?:per|for\s+(?:each|every))\s+(?:\$1\b|dollar))",
)
_CAP = re.compile(
    r"(?:on\s+)?(?:up\s+to|the\s+first)\s+\$\s*(?P<amt>[\d,]+(?:\.\d{1,2})?)\s+(?:spent\s+)?(?:in\s+)?"
    r"(?P<combined>combined\s+)?(?:eligible\s+)?(?:purchases|spend(?:ing)?)?[^.;()]*?"
    r"(?:(?:per|each|a|every)\s+(?P<period>calendar\s+year|(?:account\s+)?anniversary\s+year|year|quarter|"
    r"month|billing\s+cycle|cardmember\s+year)|(?P<annually>annually))",
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
    r"(?:[A-Z][\w.]+\s+){0,3}(?:travel\s+)?(?:portal|center|centre))|\btravel portal\b|"
    r"\b(?:on|through|via)\s+(?:all\s+purchases\s+through\s+)?(?:chase travel|capital one (?:business )?travel|"
    r"amex ?travel|american express travel)\b",
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
    "anniversary year": "annual",
    "account anniversary year": "annual",
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
    # "4% on X, 3% on dining, 2% on groceries": the categories of this rate end where the next rate begins.
    nxt = _RATE.search(rest)
    if nxt is not None:
        rest = rest[: nxt.start()]
    cats = categories_in(rest) or categories_in(text[: m.start()])
    is_base = "other" in cats and len(cats) == 1
    cats = [c for c in cats if c != "other"] or (["other"] if is_base else [])
    rr = RewardRate(rate=rate, rate_unit=unit, categories=cats, is_base=is_base, text=text.strip())
    cap = _CAP.search(text)
    if cap:
        rr.cap_cents = _dollars_to_cents(cap.group("amt"))
        rr.cap_period = (
            "annual" if cap.group("annually") else _PERIODS[re.sub(r"\s+", " ", cap.group("period").lower())]
        )
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
