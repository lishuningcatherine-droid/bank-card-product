"""Welcome-offer / bonus parsing, including amount qualifiers (brief §5.4, DESIGN §22.2).

Operates on the *offer block*: the sentence(s) holding the bonus amount plus any footnote text attached to it.
Fail-safe: if any variability phrase is present and cannot be tied to a different number, the qualifier is
``up_to``. An amount is ``exact`` only when no variability phrase is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from bankrec.parsers.period import Period, parse_period
from bankrec.parsers.placeholders import contains_placeholder


class Qualifier(StrEnum):
    exact = "exact"
    up_to = "up_to"
    starting_at = "starting_at"


VARIABILITY_PHRASES = [
    r"earn\s+up\s+to",
    r"up\s+to",
    r"as\s+high\s+as",
    r"you\s+may\s+be\s+eligible\s+for",
    r"offers?\s+may\s+vary",
    r"offers?\s+vary",
    r"may\s+vary",
    r"could\s+earn",
    r"potential(?:ly)?",
]
FLOOR_PHRASES = [r"at\s+least", r"starting\s+at", r"a\s+minimum\s+of"]
_VAR = re.compile(r"\b(?:" + "|".join(VARIABILITY_PHRASES) + r")\b", re.IGNORECASE)
_FLOOR = re.compile(r"\b(?:" + "|".join(FLOOR_PHRASES) + r")\s*$", re.IGNORECASE)

_POINTS = re.compile(
    r"(?P<n>\d{1,3}(?:,\d{3})+|\d{4,7})\s*(?:bonus\s+)?(?:(?:membership\s+rewards®?|ultimate\s+rewards®?|"
    r"venture|miles?\s+rewards)\s+)?(?P<u>points?|miles?)\b",
    re.IGNORECASE,
)
_CASH = re.compile(r"\$\s*(?P<n>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<c>\d{2}))?")
_NUMBER = re.compile(r"\$?\s*\d[\d,]*(?:\.\d+)?\s*%?")

_REQ_SPEND = re.compile(
    r"(?:spend|make|making|purchases?\s+(?:totaling|of))\s+(?:at\s+least\s+)?\$\s*(?P<n>[\d,]+)"
    r"(?:\.\d{2})?(?:\s+(?:or more\s+)?(?:on|in)\s+(?:eligible\s+|net\s+)?purchases)?",
    re.IGNORECASE,
)
_REQ_DD = re.compile(
    r"(?:direct\s+deposits?|electronic\s+deposits?)\s+(?:totaling|of|that total)\s+"
    r"(?:at\s+least\s+|\$?\s*)?\$?\s*(?P<n>[\d,]+)",
    re.IGNORECASE,
)
_REQ_NEW_MONEY = re.compile(
    r"(?:deposit|transfer)\s+(?:at\s+least\s+)?\$\s*(?P<n>[\d,]+)\s+(?:or more\s+)?"
    r"(?:in\s+)?(?:new\s+money|new\s+funds|in\s+new\s+money)",
    re.IGNORECASE,
)
_DD_COUNT = re.compile(
    r"(?P<n>\d|one|two|three|four|five)\s+(?:or more\s+)?(?:qualifying\s+)?direct\s+deposits", re.IGNORECASE
)
_WINDOW = re.compile(
    r"(?:within|in)\s+(?:the\s+)?(?:first\s+)?\d+\s*(?:days?|months?)|"
    r"(?:within|in)\s+(?:the\s+)?first\s+\w+\s+(?:days?|months?)",
    re.IGNORECASE,
)
_HOLD = re.compile(
    r"(?:maintain|keep|hold)[^.]{0,80}?for\s+(?:at\s+least\s+)?(\d+|ninety|sixty|thirty)\s+"
    r"(days?|months?)",
    re.IGNORECASE,
)
_REQ_VARY = re.compile(r"(?:spend(?:ing)?|purchase)\s+requirements?\s+(?:may\s+)?vary", re.IGNORECASE)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "thirty": 30, "sixty": 60, "ninety": 90}


@dataclass
class ParsedOffer:
    qualifier: Qualifier
    amount_min: int | None
    amount_max: int | None
    reward_unit: str  # cents | points | miles
    amount_span: tuple[int, int]
    qualifier_evidence: str | None = None
    requirement_type: str | None = None  # spend | direct_deposit_total | new_money_deposit
    requirement_qualifier: Qualifier | None = None
    requirement_min_cents: int | None = None
    requirement_max_cents: int | None = None
    requirement_span: tuple[int, int] | None = None
    required_dd_count: int | None = None
    window: Period | None = None
    window_text: str | None = None
    holding: Period | None = None
    notes: list[str] = field(default_factory=list)


def _int(tok: str) -> int:
    return int(tok.replace(",", ""))


def _reward_amount(
    block: str, requirement_spans: list[tuple[int, int]]
) -> tuple[int, str, tuple[int, int]] | None:
    """First points/miles amount, else the first cash amount that is not part of a requirement."""
    pm = _POINTS.search(block)
    if pm:
        unit = "miles" if pm.group("u").lower().startswith("mile") else "points"
        return _int(pm.group("n")), unit, (pm.start("n"), pm.end())
    for cm in _CASH.finditer(block):
        if any(s <= cm.start() < e for s, e in requirement_spans):
            continue
        cents = _int(cm.group("n")) * 100 + (int(cm.group("c")) if cm.group("c") else 0)
        return cents, "cents", (cm.start(), cm.end())
    return None


def parse_offer_block(block: str, footnotes: str = "") -> ParsedOffer | None:
    """Parse a welcome-offer or bonus block. Returns None when no reward amount is present."""
    if contains_placeholder(block):
        return None
    req_matches = [
        m for m in (_REQ_SPEND.search(block), _REQ_DD.search(block), _REQ_NEW_MONEY.search(block)) if m
    ]
    req_spans = [(m.start(), m.end()) for m in req_matches]
    amt = _reward_amount(block, req_spans)
    if amt is None:
        return None
    value, unit, span = amt

    qualifier = Qualifier.exact
    evidence: str | None = None
    for vm in _VAR.finditer(block):
        nxt = _NUMBER.search(block, vm.end())
        tied_elsewhere = (
            nxt is not None
            and nxt.start() - vm.end() <= 40
            and not (
                span[0] <= nxt.start() + (len(nxt.group(0)) - len(nxt.group(0).lstrip("$ "))) < span[1]
                or nxt.start() <= span[0] < nxt.end()
            )
        )
        if tied_elsewhere:
            continue  # e.g. "on up to $1,500 in purchases" (a cap) or "up to 5% cash back" (a rate)
        qualifier, evidence = Qualifier.up_to, vm.group(0)
        break
    if qualifier is Qualifier.exact and footnotes:
        fm = _VAR.search(footnotes)
        if fm:
            qualifier, evidence = Qualifier.up_to, fm.group(0)
    if qualifier is Qualifier.exact:
        fl = _FLOOR.search(block[max(0, span[0] - 20) : span[0]].rstrip("$ "))
        if fl:
            qualifier, evidence = Qualifier.starting_at, fl.group(0).strip()

    po = ParsedOffer(
        qualifier=qualifier,
        amount_min=None if qualifier is Qualifier.up_to else value,
        amount_max=None if qualifier is Qualifier.starting_at else value,
        reward_unit=unit,
        amount_span=span,
        qualifier_evidence=evidence,
    )

    spend, dd, nm = (_REQ_SPEND.search(block), _REQ_DD.search(block), _REQ_NEW_MONEY.search(block))
    req = spend or dd or nm
    if req is not None:
        po.requirement_type = (
            "spend" if req is spend else "direct_deposit_total" if req is dd else "new_money_deposit"
        )
        cents = _int(req.group("n")) * 100
        po.requirement_span = (req.start(), req.end())
        if _REQ_VARY.search(block) or _REQ_VARY.search(footnotes):
            po.requirement_qualifier = Qualifier.up_to
            po.requirement_max_cents = cents
        else:
            po.requirement_qualifier = Qualifier.exact
            po.requirement_min_cents = po.requirement_max_cents = cents
    cnt = _DD_COUNT.search(block)
    if cnt:
        tok = cnt.group("n").lower()
        po.required_dd_count = int(tok) if tok.isdigit() else _WORDNUM[tok]
    wm = _WINDOW.search(block)
    if wm:
        po.window = parse_period(wm.group(0))
        po.window_text = wm.group(0)
    hm = _HOLD.search(block)
    if hm:
        po.holding = parse_period(f"{hm.group(1)} {hm.group(2)}")
    return po
