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
    # "1 Avios for every $1", "3 Miles for every $1", "3 WorldPoints® points per $1" (issuer-branded unit word)
    r"\s+(?:[A-Z][A-Za-z]*®?\s+)?(?P<per>(?i:points?|miles?|avios))\s+(?i:per|for\s+(?:each|every))\s+"
    r"(?:\$1\b|(?i:dollar)))",
)
_CAP = re.compile(
    r"(?:on\s+)?(?:up\s+to|(?:the|your)\s+first)\s+\$\s*(?P<amt>[\d,]+(?:\.\d{1,2})?)(?P<k>[Kk])?\s+(?:spent\s+)?"
    r"(?:in\s+)?(?P<combined>combined\s+)?(?:eligible\s+)?(?:purchases|spend(?:ing)?)?(?:U\.S\.|[^.;()])*?"
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
    r"\b(?:on|through|via|with)\s+(?:all\s+purchases\s+through\s+)?(?:chase travel|capital one (?:business )?travel|"
    r"amex ?travel|american express travel)\b|\bin the travel center\b",
    re.IGNORECASE,
)
_UNTIL = re.compile(
    r"\b(?:through|until|thru|ending)\s+(?P<m>january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})",
    re.IGNORECASE,
)
_CHOICE = {"choice", "choice_everyday"}
_GLUED_NOTE = re.compile(r"(?<=[a-z])\d(?![\d,.%x])")
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


def parse_rate_only(text: str) -> tuple[Decimal, str] | None:
    """(rate, unit) of the first rate token, ignoring categories ("5% Cash Back on Business Essentials")."""
    m = _RATE.search(text)
    if not m:
        return None
    return Decimal(m.group("num")), ("pct" if m.group("pct") else "x")


def parse_reward_statement(text: str) -> RewardRate | None:
    """Parse one earn-rate statement. Returns None when no rate is present or the text holds a placeholder."""
    if contains_placeholder(text):
        return None
    original = text
    text = _GLUED_NOTE.sub(
        " ", text
    )  # "5% cash back2on your first $2,000": footnote marker glued to the words
    m = _RATE.search(text)
    if not m:
        return None
    rate = Decimal(m.group("num"))
    unit = "pct" if m.group("pct") else "x"
    rest = text[m.end() :]
    # "4% on X, 3% on dining, 2% on groceries": the categories of this rate end where the next rate begins.
    full_rest = rest
    nxt = _RATE.search(rest)
    if nxt is not None:
        rest = rest[: nxt.start()]
    # The portal's own name ("booked through Capital One Travel") is not the category "travel".
    # When nothing else is named ("5x on Chase Travel"), the portal stands for travel booked through it.
    cats = (
        categories_in(_PORTAL.sub(" ", rest))
        or categories_in(_PORTAL.sub(" ", text[: m.start()]))
        or categories_in(rest)
        or categories_in(text[: m.start()])
    )
    if not cats and re.search(r"\+\s*$", rest):
        # "3% cash back + 3% first-year cash back bonus in the category of your choice": the category after the
        # added (temporary) bonus also belongs to the ongoing rate; the added bonus itself is not counted.
        cats = categories_in(full_rest)
    chosen = [c for c in cats if c in _CHOICE]
    if chosen:
        # "2% on one everyday category you choose, like gas stations, grocery stores or restaurants": the listed
        # categories are options, not fixed categories (spot-check round 1).
        cats = chosen[:1]
    is_base = "other" in cats and len(cats) == 1
    cats = [c for c in cats if c != "other"] or (["other"] if is_base else [])
    rr = RewardRate(rate=rate, rate_unit=unit, categories=cats, is_base=is_base, text=original.strip())
    cap = _CAP.search(text)
    if cap:
        rr.cap_cents = _dollars_to_cents(cap.group("amt")) * (1000 if cap.group("k") else 1)  # "$50K"
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
    # Only this rate's own clause: "1.5% on every purchase ... Plus, 5% on hotels booked through Capital One
    # Business Travel" makes the 5% portal-only, not the 1.5%.
    rr.portal_only = bool(_PORTAL.search(text[: m.end()] + rest))
    until = _UNTIL.search(text)
    if until:
        rr.ends_on = date(int(until.group("y")), _MONTHS[until.group("m").lower()], int(until.group("d")))
    if not rr.categories:
        return None
    return rr


def portal_lead(text: str) -> bool:
    """True when the issuer portal is named before the statement's first rate ("Book through Capital One Business
    Travel to earn 10X miles on hotels ..., and 5X miles on flights ..."): it then covers every rate clause."""
    m = _RATE.search(text)
    return m is not None and _PORTAL.search(text[: m.start()]) is not None
