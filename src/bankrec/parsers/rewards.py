"""Reward-rate parsing for credit cards.

Input is one reward statement (a bullet or sentence). Output is a structured rate with caps, post-cap rate,
rotating/activation/portal flags and an optional end date. The caller keeps the statement's span as provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from bankrec.normalize.categories import categories_in, category_spans
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
    r"amex ?travel|american express travel)\b|\bin the travel center\b|"
    # Amex's own portal names wherever they appear ("... or Amex Travel App™"): never the category "travel"
    r"\bamex\s?travel(?:\.com)?(?:\s+app)?\b|"
    # United cards: "hotel stays when you prepay directly through Renowned Hotels and Resorts for United® Cardmembers"
    # (the program terms: "... with Renowned Hotels and Resorts for United® Cardmembers through Chase Travel")
    r"\bthrough\s+renowned\s+hotels\s+and\s+resorts\b",
    re.IGNORECASE,
)
_UNTIL = re.compile(
    r"\b(?:through|until|thru|ending)\s+(?:(?P<m>january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})"
    r"|(?P<nm>\d{1,2})/(?P<nd>\d{1,2})/(?P<ny>\d{4}|\d{2})\b)",
    re.IGNORECASE,
)
_CHOICE = {"choice", "choice_everyday"}
# Qualifiers that limit where a rate applies (spot-check round 2, A). Each is kept with the words that state it.
_DIRECT = re.compile(
    # "booked directly in the Travel Center" is the issuer portal (portal_only), not booking with the merchant
    r"\b(?:booked|purchased|bought|reserved|made)\s+direct(?:ly)?\b"
    r"(?!\s+(?:in|through|via|on)\s+(?:the\s+)?(?:[\w.]+\s+){0,3}(?:travel\s+)?(?:center|centre|portal)\b)"
    r"(?:\s+(?:with|from|through)\s+[^,.;]{1,80}?(?=[,.;]|$))?"
    r"|\bdirect(?:ly)?\s+(?:with|from)\s+(?:the\s+)?(?:airlines?|hotels?|participating\s+hotels?)\b",
    re.IGNORECASE,
)
_US_PREFIX = re.compile(r"\bU\.\s?S\.\s*$")
_US_POST = re.compile(r"\b(?:in|within)\s+the\s+(?:U\.\s?S\.|United States)(?!\s*\w)", re.IGNORECASE)
_EXCLUDING = re.compile(
    r"\b(?:excluding|excludes|except(?:\s+for)?|not\s+including)\s+[^)]{0,80}?\b"
    r"(?P<w>superstores|warehouse\s+clubs|target|walmart|costco|sam[’']s\s+club)\b[^),.;]*",
    re.IGNORECASE,
)
_SUPERSTORE_WORDS = {"superstores", "target", "walmart"}
_OR_DIRECT = re.compile(
    r"\bor\s+directly\s+(?:through|with|from)\s+(?:the\s+)?(?:airlines?|hotels?)\b"
    r"|\bdirect(?:ly)?\s+(?:with|through|from)\s+[^,.;]{1,40}?\s+or\s+(?:through\s+|on\s+)?"
    r"(?:amex\s?travel|chase\s+travel|capital\s+one\s+travel)",
    re.I,
)
_EXCLUDED_PART = re.compile(
    r"\((?:excluding|excludes|except|not\s+including)\b[^()]*\)|\b(?:excluding|not\s+including)\s+[^,;.()]*",
    re.IGNORECASE,
)
# Clause separators: ; , and . but not inside "$6,000", "1.5" or "U.S."
_SEP = re.compile(r";|,(?!\d{3})|(?<![A-Z])\.(?=\s|$)")
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
    # category -> [(kind, stating text, detail)]
    conditions: dict[str, list[tuple[str, str, str | None]]] = field(default_factory=dict)


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
    blank = lambda s: _PORTAL.sub(lambda p: " " * len(p.group(0)), s)  # noqa: E731 (keeps positions)
    regions = [blank(rest), blank(text[: m.start()]), rest, text[: m.start()]]
    # Categories named only inside an exclusion ("online grocery purchases (excluding Target®, Walmart® and wholesale
    # clubs)", "travel (excluding purchases made at hotels participating in IHG ...)") are not earning categories.
    unexcl = [_EXCLUDED_PART.sub(lambda p: " " * len(p.group(0)), r) for r in regions]
    i = next((i for i, r in enumerate(unexcl) if categories_in(r)), None)
    region, cat_region = (regions[i], unexcl[i]) if i is not None else ("", "")
    cats = categories_in(cat_region)
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
    clause = text[: m.end()] + rest
    portal = _PORTAL.search(clause)
    # "Booked through AmexTravel.com or Amex Travel App™ or directly through airlines": either channel, so not
    # portal-only; still not every airline purchase (booked direct or through the issuer)
    either = _OR_DIRECT.search(clause) if portal else None
    rr.portal_only = bool(portal) and either is None
    for c in rr.categories:
        found = _conditions_for(c, region, clause, cat_region)
        if portal and either is not None:
            found = [f for f in found if f[0] not in {"portal_only", "booked_direct"}]
            found.insert(0, ("booked_direct", _clause_around(clause, portal.start(), either.end()), None))
        elif portal:
            if not _DIRECT.search(clause):  # "booked directly in the Travel Center" is the portal
                found = [f for f in found if f[0] != "booked_direct"]
            found.insert(0, ("portal_only", portal.group(0).strip(), None))
        if rr.requires_activation and (act := _ACTIVATION.search(text)):
            found.append(("enrollment_required", _clause_around(text, act.start(), act.end()), None))
        if found:
            rr.conditions[c] = found
    rr.ends_on = end_date(text)
    if not rr.categories:
        return None
    return rr


def end_date(text: str) -> date | None:
    """The date a rate ends: "through December 31, 2026", "through 9/30/27"."""
    until = _UNTIL.search(text)
    if until is None:
        return None
    if until.group("m"):
        return date(int(until.group("y")), _MONTHS[until.group("m").lower()], int(until.group("d")))
    y = int(until.group("ny"))
    return date(y + 2000 if y < 100 else y, int(until.group("nm")), int(until.group("nd")))


def strip_exclusions(text: str) -> str:
    """``text`` without its exclusion parts ("travel (excluding purchases made at hotels participating in IHG ...)")."""
    return _EXCLUDED_PART.sub(" ", text)


def _clause_around(text: str, start: int, end: int) -> str:
    """The clause of ``text`` holding [start, end): from the previous to the next , ; or . (the stating words)."""
    seps = [mm.start() for mm in _SEP.finditer(text)]
    lo = max([s + 1 for s in seps if s < start], default=0)
    hi = min([s for s in seps if s >= end], default=len(text))
    return text[lo:hi].strip()


_DIRECT_CATEGORIES = {"airline", "hotel", "car_rental", "travel", "select_travel", "partner"}


def _conditions_for(
    code: str, region: str, clause: str, cat_region: str | None = None
) -> list[tuple[str, str, str | None]]:
    """Qualifiers that apply to category ``code`` in ``region`` (the text its categories were read from):
    "U.S." right before a mention ("at U.S. gas stations and on transit": gas only); "booked direct" / "in the U.S."
    after a mention before the next , ; or . ("flights and hotels booked direct": both; "flights booked directly,
    car rental agencies": flights only); an exclusion right after it ("grocery stores (excluding Target® and
    Walmart® purchases)")."""
    out: list[tuple[str, str, str | None]] = []
    spans = [
        (s, e) for s, e, c in category_spans(cat_region if cat_region is not None else region) if c == code
    ]

    def extra(s: int) -> bool:  # a mention inside "including ..." after the same category's own mention
        prev = max([mm.end() for mm in _SEP.finditer(region, 0, s)], default=0)
        return bool(re.search(r"\bincluding\b", region[prev:s], re.I))

    own_mentions = [sp for sp in spans if not extra(sp[0])]
    for s, e in spans:
        if own_mentions and (s, e) not in own_mentions:
            continue  # "restaurants, including takeout and delivery in the U.S.": the qualifier limits the extras only
        own = region[s:e]  # synonyms may carry the qualifier ("U.S. supermarkets", "flights booked direct")
        pre = _US_PREFIX.search(region[max(0, s - 8) : s])
        if (pre or re.match(r"U\.\s?S\.", own)) and not any(k == "us_only" for k, _, _ in out):
            out.append(("us_only", region[max(0, s - 8) + pre.start() if pre else s : e].strip(), None))
        nxt = _SEP.search(region, e)
        tail = own + region[e : nxt.start() if nxt else len(region)]
        for pat, kind in ((_DIRECT, "booked_direct"), (_US_POST, "us_only")):
            if kind == "booked_direct" and code not in _DIRECT_CATEGORIES:
                continue  # "dining when purchased directly from a restaurant" is not a travel booking channel
            if kind == "us_only" and re.search(r"\bworldwide\b", clause, re.I):
                continue  # "restaurants worldwide, including takeout and delivery in the U.S."
            if (q := pat.search(tail)) and not any(k == kind for k, _, _ in out):
                out.append((kind, _clause_around(region, s, s + q.end()), None))
        ex = _EXCLUDING.search(region[e : e + 120])
        if ex and not _SEP.search(region[e : e + ex.start()]):
            w = ex.group("w").lower()
            kind = "excludes_superstores" if w in _SUPERSTORE_WORDS else "excludes_warehouse_clubs"
            if not any(k == kind for k, _, _ in out):
                out.append((kind, ex.group(0).strip(), None))
    if not spans and code in _DIRECT_CATEGORIES and (q := _DIRECT.search(clause)):
        out.append(("booked_direct", q.group(0).strip(), None))
    return out


def portal_lead(text: str) -> bool:
    """True when the issuer portal is named before the statement's first rate ("Book through Capital One Business
    Travel to earn 10X miles on hotels ..., and 5X miles on flights ..."): it then covers every rate clause."""
    m = _RATE.search(text)
    return m is not None and _PORTAL.search(text[: m.start()]) is not None
