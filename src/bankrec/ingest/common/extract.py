"""Shared, bank-agnostic extractors. Every value goes through :class:`ExtractionContext.field`, so a value is kept
only when its quoted source text exists in the snapshot text (provenance guard)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from bankrec.ingest.common.html import PageDoc, table_rows
from bankrec.model import (
    ApyTier,
    BenefitRec,
    ExtractionContext,
    FeeWaiver,
    NullReason,
    OfferRec,
    OfferTier,
    RateCondition,
    RewardRateRec,
    Sourced,
)
from bankrec.parsers.money import find_amounts, parse_fee_schedule, parse_money
from bankrec.parsers.offers import Qualifier, parse_offer_block
from bankrec.parsers.percent import parse_percent, parse_percent_range
from bankrec.parsers.period import parse_period
from bankrec.parsers.placeholders import contains_placeholder, is_placeholder
from bankrec.parsers.rewards import (
    _MONTHS,
    RewardRate,
    end_date,
    parse_rate_only,
    parse_reward_statement,
    portal_lead,
)

US_STATES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
]

# Labels used by U.S. issuers in pricing tables (Schumer box) and account summaries.
LABELS: dict[str, list[str]] = {
    "annual_fee": [r"annual (?:membership )?fee"],
    "purchase_apr": [
        r"(?:apr|annual percentage rate) for purchases",
        r"purchase apr",
        r"regular apr",
        r"ongoing apr",
    ],
    "bt_apr": [r"balance transfer apr", r"apr for balance transfers"],
    "cash_apr": [r"cash advance apr", r"apr for cash advances"],
    "bt_fee": [r"balance transfers?(?: fee)?$", r"balance transfer fee"],
    "cash_fee": [r"cash advances?(?: fee)?$", r"cash advance fee"],
    "ftf": [r"foreign (?:purchase )?transaction(?:s)?(?: fee)?"],
    "monthly_fee": [r"monthly (?:maintenance|service) fee", r"monthly fee"],
    "min_opening": [r"minimum (?:opening )?deposit(?: to open)?", r"minimum to open", r"opening deposit"],
    "min_balance": [r"minimum balance(?: to (?:earn|obtain) (?:the )?apy)?", r"minimum daily balance"],
    "overdraft": [r"overdraft(?: fee| policy| services?)?"],
    "apy": [r"annual percentage yield", r"\bapy\b"],
    "au": [r"authorized users?", r"additional cards?"],
}


def _label_match(label: str, key: str) -> bool:
    label = label.strip().rstrip(":").lower()
    return any(re.fullmatch(p, label) or re.match(p + r"\b", label) for p in LABELS[key])


def labelled(doc: PageDoc, key: str) -> tuple[str, str, str] | None:
    """Value for a label. Returns (value_text, evidence_text, method). Tables first, then "Label: value" lines."""
    for lab, val in table_rows(doc):
        if _label_match(lab, key):
            return val, val, "table_cell"
    for line in doc.text.split("\n"):
        m = re.match(r"^(?P<label>[^:]{3,60}):\s*(?P<val>.+)$", line)
        if m and _label_match(m.group("label"), key):
            return m.group("val"), line, "label_regex"
    return None


def first_line(doc: PageDoc, pattern: str, flags: int = re.IGNORECASE) -> str | None:
    for line in doc.text.split("\n"):
        if re.search(pattern, line, flags):
            return line
    return None


def lines(doc: PageDoc, pattern: str, flags: int = re.IGNORECASE) -> list[str]:
    return [ln for ln in doc.text.split("\n") if re.search(pattern, ln, flags)]


def placeholder_or_missing(ctx: ExtractionContext, raw: str | None) -> Sourced[Any]:
    if raw is not None and (is_placeholder(raw) or contains_placeholder(raw)):
        return ctx.field(None, None, null_reason=NullReason.requires_render)
    return ctx.field(None, None)


# ----------------------------------------------------------------------------------------------- credit cards


def card_fees_and_rates(doc: PageDoc, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
    out: dict[str, Sourced[Any]] = {}
    af = labelled(doc, "annual_fee")
    if af is None:
        line = first_line(doc, r"\b(?:no annual fee|\$\d[\d,]*\s+annual fee|annual fee (?:is|of)\s+\$\d)")
        af = (line, line, "free_text") if line else None
    if af:
        sched = parse_fee_schedule(af[0])
        if sched.ongoing_cents is None:
            out["annual_fee_cents"] = placeholder_or_missing(ctx, af[0])
        else:
            out["annual_fee_cents"] = ctx.field(sched.ongoing_cents, af[1], method=af[2], name="annual_fee")
            if sched.intro_cents is not None:
                out["intro_annual_fee_cents"] = ctx.field(sched.intro_cents, af[1], method=af[2])
                p = parse_period(sched.intro_text or "") if sched.intro_text else None
                # An annual fee is billed per year, so "first year" / "first 2 years" are exact month counts.
                months = (
                    (p.value if p.unit == "months" else p.value * 12 if p.unit == "years" else None)
                    if p
                    else None
                ) or (12 if sched.intro_text and "first year" in sched.intro_text else None)
                out["intro_annual_fee_months"] = ctx.field(months, af[1], method=af[2])
            else:
                out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
                out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
    sched_line = first_line(
        doc,
        r"(?:beginning|starting|effective)\s+\w+\s+\d{1,2},?\s+\d{4}.{0,60}annual fee"
        r".{0,30}\$\d",
    )
    if sched_line:
        dm = re.search(
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+"
            r"(\d{1,2}),?\s+(\d{4})",
            sched_line,
            re.IGNORECASE,
        )
        amounts = find_amounts(sched_line)
        if dm and amounts:
            out["annual_fee_effective_date"] = ctx.field(
                date(int(dm.group(3)), _MONTHS[dm.group(1).lower()], int(dm.group(2))), sched_line
            )
            out["future_annual_fee_cents"] = ctx.field(amounts[-1].cents, sched_line)

    pa = labelled(doc, "purchase_apr")
    if pa:
        rng = parse_percent_range(_after_intro(pa[0]))
        if rng is None:
            out["purchase_apr_min_pct"] = placeholder_or_missing(ctx, pa[0])
            out["purchase_apr_max_pct"] = placeholder_or_missing(ctx, pa[0])
        else:
            out["purchase_apr_min_pct"] = ctx.field(rng.low, pa[1], method=pa[2])
            out["purchase_apr_max_pct"] = ctx.field(rng.high, pa[1], method=pa[2])
            out["purchase_apr_variable"] = ctx.field(rng.variable, pa[1], method=pa[2])
        intro = _intro_apr(pa[0])
        if intro:
            out["intro_purchase_apr_pct"] = ctx.field(intro[0], pa[1], method=pa[2])
            out["intro_purchase_apr_months"] = ctx.field(intro[1], pa[1], method=pa[2])
    if "intro_purchase_apr_pct" not in out:
        line = first_line(doc, r"\b0%\s+intro(?:ductory)?\s+apr\b.{0,40}purchases")
        intro = _intro_apr(line) if line else None
        if line and intro:
            out["intro_purchase_apr_pct"] = ctx.field(intro[0], line, method="free_text")
            out["intro_purchase_apr_months"] = ctx.field(intro[1], line, method="free_text")
        else:
            out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
            out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=NullReason.not_applicable)

    bt = labelled(doc, "bt_apr")
    if bt:
        rng = parse_percent_range(_after_intro(bt[0]))
        if rng:
            out["bt_apr_min_pct"] = ctx.field(rng.low, bt[1], method=bt[2])
            out["bt_apr_max_pct"] = ctx.field(rng.high, bt[1], method=bt[2])
        intro = _intro_apr(bt[0])
        if intro:
            out["intro_bt_apr_pct"] = ctx.field(intro[0], bt[1], method=bt[2])
            out["intro_bt_apr_months"] = ctx.field(intro[1], bt[1], method=bt[2])
    ca = labelled(doc, "cash_apr")
    if ca:
        rng = parse_percent_range(ca[0])
        if rng:
            out["cash_apr_pct"] = ctx.field(rng.high, ca[1], method=ca[2])
    for key, pct_name, min_name in (
        ("bt_fee", "bt_fee_pct", "bt_fee_min_cents"),
        ("cash_fee", "cash_fee_pct", "cash_fee_min_cents"),
    ):
        fee = labelled(doc, key)
        if fee and re.search(r"\d", fee[0]) and not contains_placeholder(fee[0]):
            pct = parse_percent(fee[0])
            amt = parse_money(fee[0])
            if pct is not None:
                out[pct_name] = ctx.field(pct, fee[1], method=fee[2])
            if amt is not None:
                out[min_name] = ctx.field(amt, fee[1], method=fee[2])
    ftf = labelled(doc, "ftf")
    if ftf is None:
        line = first_line(doc, r"\bno foreign transaction fees?\b")
        ftf = (line, line, "free_text") if line else None
    if ftf:
        if re.search(r"\b(?:none|no foreign transaction fee|\$0)\b", ftf[0], re.IGNORECASE):
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), ftf[1], method=ftf[2])
        else:
            pct = parse_percent(ftf[0])
            out["foreign_tx_fee_pct"] = (
                ctx.field(pct, ftf[1], method=ftf[2])
                if pct is not None
                else placeholder_or_missing(ctx, ftf[0])
            )
    dep = first_line(doc, r"(?:minimum\s+)?security\s+deposit")
    if dep:
        amt = parse_money(dep)
        if amt is not None:
            out["secured_min_deposit_cents"] = ctx.field(amt, dep, method="free_text")
    au = labelled(doc, "au")
    if au:
        txt = au[0]
        cnt = re.search(r"(?:up to|first)\s+(\d+)\s+(?:additional\s+)?(?:cards|users)", txt, re.IGNORECASE)
        if re.search(r"\b(?:no (?:annual )?fee|\$0)\b", txt, re.IGNORECASE):
            out["au_fee_cents"] = ctx.field(0, au[1], method=au[2])
            if cnt:
                out["au_free_count"] = ctx.field(int(cnt.group(1)), au[1], method=au[2])
        amounts = [a for a in find_amounts(txt) if a.cents > 0]
        if amounts:
            out["au_fee_cents"] = ctx.field(amounts[-1].cents, au[1], method=au[2])
    return out


def _after_intro(text: str) -> str:
    """For "0% intro APR for 15 months, then 19.24% - 29.24% Variable" return the part after "then"."""
    m = re.search(r"\b(?:then|after that,?)\b(.*)$", text, re.IGNORECASE)
    return m.group(1) if m else text


def _intro_apr(text: str | None) -> tuple[Decimal, int] | None:
    if not text:
        return None
    m = re.search(
        r"(\d{1,2}(?:\.\d+)?)%\s+intro(?:ductory)?\s+apr[^.]{0,60}?(?:for|on purchases for|on balance "
        r"transfers for)\s+(?:the\s+)?(?:first\s+)?(\d{1,2})\s+(months|billing cycles)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    return Decimal(m.group(1)), int(m.group(2))


_RATE_TOKEN = re.compile(
    r"(?<![\w$.,])\d{1,2}(?:\.\d{1,2})?\s*(?:%|[xX]\b|\s+(?:points?|miles?|avios)\s+(?:per|for\s+(?:each|every))\b)",
    re.IGNORECASE,  # "3 Avios for every $1"
)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def has_rate_token(text: str) -> bool:
    """True when the statement states an earn rate ("3%", "2X", "2 points per $1")."""
    return _RATE_TOKEN.search(text) is not None


def split_rate_clauses(text: str) -> list[str]:
    """Split "Earn 2 points ... on travel and dining and unlimited 1.5 points ... on all other purchases" into one
    clause per rate, so each rate keeps only its own categories. A rate introduced by "then" (a post-cap rate) stays
    with its clause."""
    starts = [m.start() for m in _RATE_TOKEN.finditer(text)]
    # never cut inside a range ("18.49%–27.99%", "3 to 5 points") or before a post-cap "then 1%"
    cuts = [s for s in starts[1:] if not re.search(r"(?:\bthen|[–-]|\bto)\s*$", text[:s], re.IGNORECASE)]
    parts, prev = [], 0
    for c in cuts:
        parts.append(text[prev:c])
        prev = c
    parts.append(text[prev:])
    return [p.strip(" ,;") for p in parts if p.strip(" ,;")]


def reward_rates(statements: Iterable[str], ctx: ExtractionContext) -> list[Sourced[RewardRateRec]]:
    out: list[Sourced[RewardRateRec]] = []
    # One clause per rate: "1.5% on every purchase ... Plus, earn unlimited 5% on hotels ..." holds two rates.
    pieces = [(p.strip(), portal_lead(st), st) for st in statements for p in split_rate_clauses(st)]
    prev: tuple[str, RewardRate] | None = None
    for st, lead, whole in pieces:
        # the words introducing the next, back-referring rate are not part of this one ("2X at grocery stores.
        # Through December 31, 2026, these purchases will earn" | "3X points per $1 spent")
        rr = parse_reward_statement(_BACK_REF_TAIL.sub("", st))
        if rr is None:
            rr = _back_reference(st, whole, prev)
        if rr is None:
            continue
        prev = (whole, rr)
        rr.portal_only = rr.portal_only or lead
        for cat in rr.categories:
            conds = rate_conditions(rr.conditions.get(cat, []), st)
            if lead and not any(c.kind == "portal_only" for c in conds):
                conds.insert(0, RateCondition(kind="portal_only", text=_lead_text(whole)))
            rec = RewardRateRec(
                category=cat,
                rate=rr.rate,
                rate_unit=rr.rate_unit,
                cap_cents=rr.cap_cents,
                cap_period=rr.cap_period,
                cap_combined=rr.cap_combined,
                cap_group=(st if rr.cap_combined else None),
                post_cap_rate=rr.post_cap_rate,
                is_rotating=rr.is_rotating,
                requires_activation=rr.requires_activation,
                portal_only=rr.portal_only,
                ends_on=rr.ends_on,
                text=rr.text,
                conditions=conds,
            )
            out.append(ctx.field(rec, st, method="free_text", name=f"reward:{cat}"))
    return [s for s in out if s.present]


_PROGRAM_PARA = re.compile(
    r"^(?:Earning in the Rewards Program|How you can earn (?:points|cash back))\b", re.I
)
_PROGRAM_SKIP = re.compile(
    r"(?:points|miles|rewards)\s+on\s+purchases\s+of\s+products\s+and\s+services|balance\s+transfers\s+made|"
    r"tier\s+qualifying|for\s+each\s+\$[\d,]{2,}\b(?!\s*spent)",
    re.IGNORECASE,
)
_RATE_IN_PAREN = re.compile(r"\([^()]*\d+(?:\.\d+)?\s*(?:%|points?|miles?)[^()]*\)", re.IGNORECASE)
PURCHASE_SIZE = re.compile(r"\bpurchases?\s+totaling\s+\$[\d,]+\s+or\s+more", re.IGNORECASE)


def is_program_paragraph(line: str) -> bool:
    return bool(_PROGRAM_PARA.search(line))


def program_statements(text: str) -> list[tuple[str, str]]:
    """The issuer's rewards-program terms printed on the product page (Chase: "Earning in the Rewards Program: ...
    5 points ("5X points"): You'll earn 5 points for each $1 spent on qualifying purchases made at hotels
    participating in IHG One Rewards. ..."): (sentence as printed, sentence prepared for parsing) per "You'll earn"
    clause. The clause headings are not used (they can disagree with the sentence: "5% Cash Back: You'll earn 1.5%
    ..."); "(N additional points on top of ...)" asides and the generic definition of a purchase are dropped."""
    out: list[tuple[str, str]] = []
    for ln in text.split("\n"):
        if not _PROGRAM_PARA.search(ln):
            continue
        starts = [m.start() for m in re.finditer(r"You[’']ll earn\s", ln)]
        for i, a0 in enumerate(starts):
            seg = ln[a0 : starts[i + 1] if i + 1 < len(starts) else len(ln)]
            e = re.search(r"\.(?=\s)", seg)
            sent = (seg[: e.end()] if e else seg).strip()
            if _PROGRAM_SKIP.search(sent):
                continue
            prep = _RATE_IN_PAREN.sub(" ", sent)
            prep = re.sub(r"\b(points?|miles?|rewards)\s+total\s+for\b", r"\1 for", prep, flags=re.I)
            prep = re.sub(r"\bCash\s+Back\s+rewards\b", "cash back", prep, flags=re.I)
            if re.search(r"for\s+each\s+\$1(?:\s+spent)?\s*\.?$", prep.strip()):
                prep = (
                    prep.rstrip(". ") + " on all other purchases."
                )  # "You'll earn 1 point for each $1 spent."
            out.append((sent, norm_ws(prep)))
    return out


_TILE_THIS_CARD = re.compile(r"^That[’']s\s+(\d{1,2}(?:\.\d+)?)X\s+points\s+with\s+this\s+card\b", re.I)


def card_tiles(text: str) -> list[tuple[str, str]]:
    """ "Up to 17X total points at IHG® Hotels and Resorts" / "That's 5X points with this card.*": the card's own rate
    is the second line, its category the heading. Returns (span: heading + line, statement to parse)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out: list[tuple[str, str]] = []
    for i, ln in enumerate(lines[1:], 1):
        m = _TILE_THIS_CARD.match(ln)
        if not m:
            continue
        head = re.sub(r"^(?:earn\s+)?up\s+to\s+\d+X\s+total\s+points\s*", "", lines[i - 1], flags=re.I)
        out.append((f"{lines[i - 1]} {ln}", f"{m.group(1)}X points {head}"))
    return out


_BACK_REF_TAIL = re.compile(
    r"\.?\s*\bthrough\b[^.]{0,40},\s+these\s+purchases\s+will\s+earn\s*$", re.IGNORECASE
)


def _back_reference(st: str, whole: str, prev: tuple[str, RewardRate] | None) -> RewardRate | None:
    """ "Through December 31, 2026, these purchases will earn 3X points per $1 spent": a rate for the previous clause's
    categories (same statement), ending on the stated date."""
    if prev is None or prev[0] != whole or not re.search(r"\bthese\s+purchases\s+will\s+earn\b", whole, re.I):
        return None
    only = parse_rate_only(st)
    until = re.search(r"\bthrough\s+[^.]{3,40}?,\s+these\s+purchases\s+will\s+earn\b", whole, re.I)
    if only is None or until is None:
        return None
    return RewardRate(
        rate=only[0],
        rate_unit=only[1],
        categories=list(prev[1].categories),
        ends_on=end_date(until.group(0)),
        text=whole.strip(),
    )


def rate_conditions(found: list[tuple[str, str, str | None]], statement: str) -> list[RateCondition]:
    """Parsed qualifiers as records. The stating words must be part of the statement (the located span), else the
    statement itself is quoted."""
    out: list[RateCondition] = []
    st = norm_ws(statement).lower()
    for kind, text, detail in found:
        quote = text if norm_ws(text).lower() in st else statement
        out.append(RateCondition(kind=kind, text=norm_ws(quote), detail=detail))
    return out


def _lead_text(statement: str) -> str:
    """The words before the first rate ("Book through Capital One Business Travel to earn")."""
    m = re.search(r"\d", statement)
    return norm_ws(statement[: m.start()] if m else statement)


_EXCL_SENTENCE = re.compile(
    r"(?P<a>superstores|warehouse\s+clubs|discount\s+stores)[^.]{0,120}?\b(?:are\s+not|aren[’']t|is\s+not|do\s+not|don[’']t|"
    r"not)\b[^.]{0,40}?\b(?:considered|included|qualify|count)[^.]{0,40}?\b(?P<c>supermarkets?|grocery\s+stores?|gas\s+stations?)"
    r"|(?P<c2>supermarkets?|grocery\s+stores?|gas\s+stations?)[^.]{0,40}?\b(?:do(?:es)?\s+not\s+include|exclud(?:e|es|ing))\b"
    r"[^.]{0,100}?(?P<a2>superstores|warehouse\s+clubs|discount\s+stores)",
    re.IGNORECASE,
)


def category_exclusions(text: str) -> list[tuple[str, RateCondition]]:
    """(category, condition) for each page sentence excluding superstores / warehouse clubs from groceries or gas
    ("Superstores, warehouse clubs ... are not considered supermarkets"). Every store type the sentence names is a
    separate condition on the categories it names."""
    out: list[tuple[str, RateCondition]] = []
    for ln in text.split("\n"):
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if not _EXCL_SENTENCE.search(sent):
                continue
            low = sent.lower()
            cats = [
                cat
                for cat, words in (("groceries", ("supermarket", "grocery")), ("gas", ("gas station",)))
                if any(w in low for w in words)
            ]
            kinds = [
                k
                for k, w in (
                    ("excludes_superstores", "superstore"),
                    ("excludes_warehouse_clubs", "warehouse club"),
                )
                if w in low
            ]
            for cat in cats:
                for k in kinds:
                    out.append((cat, RateCondition(kind=k, text=norm_ws(sent))))
    return out


def reward_currency(rates: list[Sourced[RewardRateRec]], text: str) -> tuple[str | None, str | None]:
    units = {r.value.rate_unit for r in rates if r.value}
    if units == {"pct"}:
        return "cashback", None
    if "x" in units:
        lowered = text.lower()
        if re.search(r"\bmiles\b", lowered) and not re.search(r"\bpoints\b", lowered):
            return "miles", None
        return "points", None
    return None, None


_CREDIT = re.compile(
    r"(?P<up>up to\s+)?\$(?P<amt>[\d,]+)\s+(?:in\s+)?(?P<per>monthly|annual|annually|yearly|semi-?annual|quarterly)?\s*"
    r"(?:\w+\s+){0,4}?(?:statement\s+)?credits?",
    re.IGNORECASE,
)


# "$20 annual statement credit for 11 consecutive months of purchases" / "... after $5,000 in purchases made through
# the Travel Center when you use your card"
_CREDIT_CONDITION = re.compile(r"\s*\b(?:for|after|following|when)\s+[^.]{3,120}", re.I)


def credits(statements: Iterable[str], ctx: ExtractionContext) -> list[Sourced[BenefitRec]]:
    out: list[Sourced[BenefitRec]] = []
    for st in statements:
        m = _CREDIT.search(st)
        if not m:
            continue
        per_word = (m.group("per") or "").lower()
        period = None
        years = None
        if per_word.startswith("month") or re.search(r"\b(?:each|every|per|a)\s+month\b", st, re.IGNORECASE):
            period = "monthly"
        elif per_word.startswith("quarter") or re.search(r"\beach quarter\b", st, re.IGNORECASE):
            period = "quarterly"
        elif per_word.startswith("semi") or re.search(
            r"\bsemi-?annual|twice a year|every six months\b", st, re.I
        ):
            period = "semiannual"
        elif per_word in {"annual", "annually", "yearly"} or re.search(
            r"\b(?:each|every|per|a)\s+(?:calendar\s+|cardmember\s+)?year\b|\bannual(?:ly)?\b", st, re.I
        ):
            period = "annual"
        my = re.search(r"every\s+(\d|four|five)\s+years", st, re.IGNORECASE)
        if my:
            period, years = (
                "multi_year",
                {"four": 4, "five": 5}.get(my.group(1).lower()) or int(my.group(1)),
            )
        restriction = re.search(
            r"\b(?:at|with|for|on)\s+((?:select\s+|eligible\s+)?[A-Z][\w&'.®-]*(?:\s+[A-Z][\w&'"
            r".®-]*){0,4})",
            st,
        )
        btype = "statement_credit"
        for word, t in (
            ("travel", "travel"),
            ("hotel", "hotel"),
            ("airline", "airline"),
            ("dining", "dining"),
            ("grocer", "grocery"),
            ("gas", "gas"),
            ("stream", "entertainment"),
            ("entertainment", "entertainment"),
            ("transit", "transit"),
            ("rideshare", "transit"),
            ("uber", "transit"),
        ):
            if word in st.lower():
                btype = t
                break
        rec = BenefitRec(
            benefit_type=btype,
            name=st.strip()[:120],
            monetizable=period is not None,
            amount_cents=int(m.group("amt").replace(",", "")) * 100,
            period=period,
            period_years=years,
            merchant_restriction=restriction.group(1) if restriction else None,
            enrollment_required=bool(re.search(r"\benroll(?:ment)?\b", st, re.IGNORECASE)),
            condition=(c.group(0).strip() if (c := _CREDIT_CONDITION.match(st[m.end() :])) else None),
            text=st,
        )
        out.append(ctx.field(rec, st, method="free_text", name="credit"))
    return [s for s in out if s.present]


def named_benefits(statements: Iterable[str], ctx: ExtractionContext) -> list[Sourced[BenefitRec]]:
    out: list[Sourced[BenefitRec]] = []
    for st in statements:
        btype = "other"
        for word, t in (
            ("lounge", "travel"),
            ("travel", "travel"),
            ("hotel", "hotel"),
            ("bag", "airline"),
            ("boarding", "airline"),
            ("airline", "airline"),
            ("dining", "dining"),
            ("rental car", "travel"),
            ("insurance", "travel"),
            ("ticket", "entertainment"),
            ("presale", "entertainment"),
            ("transit", "transit"),
        ):
            if word in st.lower():
                btype = t
                break
        rec = BenefitRec(benefit_type=btype, name=st.strip()[:120], monetizable=False, text=st)
        out.append(ctx.field(rec, st, method="free_text", name="benefit"))
    return [s for s in out if s.present]


_RECURRING_CREDIT = re.compile(r"\b(?:annual|yearly|each\s+year)\s+statement\s+credit\b", re.IGNORECASE)


def offer(
    block: str,
    footnotes: str,
    ctx: ExtractionContext,
    *,
    offer_type: str,
    offer_url: str,
    terms_url: str | None = None,
    tiers: list[str] | None = None,
    note: str | None = None,
    evidence: str | None = None,
) -> Sourced[OfferRec] | None:
    """``evidence``: the located span when ``block`` also carries context lines (see ``offer_context``)."""
    if _RECURRING_CREDIT.search(block):
        return None  # "Earn a $50 annual statement credit after $5,000 in purchases ..." is a yearly benefit
    po = parse_offer_block(block, footnotes)
    if po is None:
        return None
    tier_recs: list[OfferTier] = []
    for t in tiers or []:
        tp = parse_offer_block(t)
        if tp and tp.qualifier is Qualifier.exact and tp.amount_max is not None:
            tier_recs.append(
                OfferTier(
                    amount=tp.amount_max,
                    requirement_min_cents=tp.requirement_min_cents,
                    requirement_max_cents=tp.requirement_max_cents,
                    text=t,
                    window_days=tp.window.days if tp.window else None,
                    window_count=tp.window.value if tp.window else None,
                    window_unit=tp.window.unit if tp.window else None,
                )
            )
            # A headline without its own requirement/window inherits them from the explicit tiers.
            if po.requirement_type is None:
                po.requirement_type = tp.requirement_type
            if po.window is None and tp.window is not None:
                po.window, po.window_text = tp.window, tp.window_text
            if po.required_dd_count is None:
                po.required_dd_count = tp.required_dd_count
    exp = re.search(
        r"(?:expires?|ends?|offer (?:ends|expires))\s+(?:on\s+)?(january|february|march|april|may|june|"
        r"july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        block + " " + footnotes,
        re.IGNORECASE,
    )
    exp_numeric = _NUMERIC_END.search(block + " " + footnotes)
    open_by = re.search(
        r"open\s+(?:a\s+new\s+\w+\s+account\s+)?by\s+(january|february|march|april|may|june|july|"
        r"august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        block + " " + footnotes,
        re.IGNORECASE,
    )
    # "after you open an American Express® Rewards Checking account by 02/01/2027"
    open_by_num = re.search(
        r"\bopen\b[^.]{0,100}?\baccount\b[^.]{0,20}?\bby\s+(\d{1,2})/(\d{1,2})/(\d{4})\b",
        block,
        re.IGNORECASE,
    )
    promo = re.search(r"(?:promo(?:tion)?|offer|bonus)\s+code\s+([A-Z0-9]{4,20})\b", block + " " + footnotes)
    restrictions = [
        s.strip()
        for s in re.split(r"(?<=[.])\s+", footnotes)
        if re.search(
            r"not (?:available|eligible)|once per|lifetime|within the (?:last|past)|new "
            r"(?:card ?members|customers)",
            s,
            re.IGNORECASE,
        )
    ]
    spend_tiers = _spend_tiers(block)
    if (
        po.qualifier.value == "up_to"
        and len(spend_tiers) >= 2
        and po.amount_max == sum(t.amount for t in spend_tiers)
        and all(t.text for t in spend_tiers)
    ):
        # "Earn up to 80,000 ... Earn 70,000 after you spend $3,000 ... Plus, earn 10,000 after you add an
        # authorized user": the tiers add up to the headline, so the offer is tiered, not an unexplained "up to".
        tier_recs = spend_tiers
        po.qualifier = Qualifier.tiered
        po.amount_min = spend_tiers[0].amount
    try:
        rec = OfferRec(
            offer_type=offer_type,
            reward_unit=po.reward_unit,
            amount_qualifier=po.qualifier.value,
            amount_min=po.amount_min,
            amount_max=po.amount_max,
            requirement_type=po.requirement_type,
            requirement_qualifier=po.requirement_qualifier.value if po.requirement_qualifier else None,
            requirement_min_cents=po.requirement_min_cents,
            requirement_max_cents=po.requirement_max_cents,
            required_dd_count=po.required_dd_count,
            qualification_window_days=po.window.days if po.window else None,
            qualification_window_months=po.window.months if po.window else None,
            qualification_window_count=po.window.value if po.window else None,
            qualification_window_unit=po.window.unit if po.window else None,
            qualification_window_text=po.window_text,
            holding_period_days=po.holding.days if po.holding else None,
            holding_period_count=po.holding.value if po.holding else None,
            holding_period_unit=po.holding.unit if po.holding else None,
            expiration_date=_d(exp) or _numeric_date(exp_numeric),
            open_by_date=_d(open_by) or _numeric_date(open_by_num),
            promo_code=promo.group(1) if promo else None,
            audience="public",
            eligibility_restrictions=" ".join(restrictions) or None,
            offer_url=offer_url,
            terms_url=terms_url,
            verbatim_text=(block + (" " + footnotes if footnotes else "")).strip(),
            qualifier_evidence=po.qualifier_evidence,
            note=note,
            tiers=tier_recs,
        )
    except ValueError:
        return None
    return ctx.field(rec, evidence or block, method="label_regex", name="offer")


_NUMERIC_END = re.compile(
    r"(?:expires?|ends?|offer (?:ends|expires)|through|until|apply by|by)\s+(?:on\s+)?(\d{1,2})/(\d{1,2})/(\d{2}(?:\d{2})?)\b",
    re.IGNORECASE,
)
_TIER = re.compile(
    # "... (PQP) Earn 90,000 bonus miles ..." and "Earn 500 PQP after first purchase and 80,000 bonus miles after ..."
    r"(?:(?:^|[.*†!)]\s*|\bplus,?\s+|\band\s+)(?:earn|get)\s+|\band\s+)(?:an?\s+)?(?P<add>additional\s+|another\s+)?"
    r"(?P<amt>[\d,]{5,}|\$[\d,]+)\s*(?:bonus\s+)?(?:points|miles|avios|cash back|cash bonus|bonus)?[^.]*?"
    r"\b(?:after|once|when)\s+you\s+(?:"
    r"(?:spend|make)\s+(?:an?\s+)?(?P<inc>additional\s+|another\s+)?\$(?P<req>[\d,]+)"
    r"|(?P<other>add|refer|open|enroll)[^.]*)",
    re.IGNORECASE,
)


def _spend_tiers(block: str) -> list[OfferTier]:
    """The tiers of a multi-part welcome offer, in page order (empty when the block states one amount)."""
    out: list[OfferTier] = []
    for m in _TIER.finditer(block):
        amt = int(m.group("amt").replace("$", "").replace(",", "")) * (
            100 if m.group("amt").startswith("$") else 1
        )
        if m.group("other"):
            out.append(OfferTier(amount=amt, requirement_min_cents=None, text=m.group(0).strip()))
            continue
        end = block.find(".", m.end())
        w = re.search(
            r"(?:within|in)\s+(?:the\s+|your\s+)?(?:first\s+)?\d+\s*(?:days?|months?|billing\s+cycles?)",
            block[m.start() : end if end != -1 else len(block)],
            re.IGNORECASE,
        )
        p = parse_period(w.group(0)) if w else None
        out.append(
            OfferTier(
                amount=amt,
                requirement_min_cents=int(m.group("req").replace(",", "")) * 100,
                text=m.group(0).strip(),
                window_days=p.days if p else None,
                window_count=p.value if p else None,
                window_unit=p.unit if p else None,
                incremental=bool(m.group("inc")),
            )
        )
    return out


_AMOUNT_TOKEN = re.compile(r"\$[\d,]{3,}|\b\d{1,3},\d{3}\b")
_FOLLOW = re.compile(r"^(?:earn|plus|get)\b", re.IGNORECASE)
_SPEND_PHRASE = re.compile(
    r"\b(?:spend|spending|make|purchases totaling|net purchases totaling)\b[^.]{0,40}\$[\d,]+", re.I
)


_SIGNAL_AMT = re.compile(
    r"\b(?:earn|get|bonus)\b[^\n]{0,80}?(?:\$[\d,]{3,}|\b\d{1,3},\d{3}\s+(?:bonus\s+)?(?:points|miles|avios)\b)",
    re.I,
)
_SIGNAL_WINDOW = re.compile(r"\b\d+\s*(?:days?|months?)\b", re.I)


def offer_signal(text: str) -> str | None:
    """An offer block on the page: a bonus amount with a spending requirement and a window in the same or the next
    line. Returns the text that triggered it (for the review note)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    for i, ln in enumerate(lines):
        if not _SIGNAL_AMT.search(ln):
            continue
        win = " ".join(lines[i : i + 2])
        if _SPEND_PHRASE.search(win) and _SIGNAL_WINDOW.search(win) and not re.search(r"\brefer", win, re.I):
            return win
    return None


_BT_FEE = re.compile(
    r"balance\s+transfer\s+fee\s+(?:of|is|:)?\s*(?:either\s+)?(?P<pct>\d{1,2}(?:\.\d{1,2})?)%\s+of\s+(?:each|the)\s+"
    r"(?:transfer|amount)[^.$]{0,40}?(?:,|\s+or)\s*\$(?P<min>\d{1,3}(?:\.\d{2})?)\s+(?:minimum|whichever)",
    re.IGNORECASE,
)
_BT_WINDOW = re.compile(
    r"applies\s+to\s+balance\s+transfers\s+made\s+within\s+(?P<n>\d{1,3})\s+days\s+of\s+account\s+opening",
    re.I,
)


def bt_fee_sentence(text: str) -> tuple[Decimal, int | None, str] | None:
    """(fee %, minimum cents, sentence) from "Balance Transfer fee of 5% of each transfer amount, $5 minimum will
    apply." or "... either 5% of the amount of each transfer or $5, whichever is greater"."""
    for ln in text.split("\n"):
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if m := _BT_FEE.search(sent):
                return Decimal(m.group("pct")), round(float(m.group("min")) * 100), sent.strip()
    return None


def bt_window(text: str) -> tuple[int, str] | None:
    """(days, sentence): "The 0% introductory APR applies to balance transfers made within 60 days of account opening
    and is valid for the first 21 billing cycles." (days as stated; never converted)"""
    for ln in text.split("\n"):
        for sent in re.split(r"(?<=[a-z0-9)][.!?])\s+", ln):
            if m := _BT_WINDOW.search(sent):
                return int(m.group("n")), sent.strip()
    return None


_NO_FTF = re.compile(
    r"\b(?:does\s+not\s+(?:have|charge)|doesn[’']t\s+(?:have|charge)|has\s+no|charges\s+no|there\s+(?:are|is)\s+no)\s+"
    r"(?:any\s+)?(?:foreign\s+transaction\s+fees?|fees?\s+on\s+foreign\s+(?:transactions|purchases))",
    re.IGNORECASE,
)


def _name_core(name: str) -> str:
    s = re.sub(r"[®™℠*†‡¤]", "", name).lower()
    s = re.sub(r"\b(?:credit\s+card|card)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def stated_no_ftf(text: str, name: str) -> str | None:
    """A sentence, typically an FAQ or benefit-panel answer, saying this card has no foreign transaction fees and
    naming it ("The Hilton Honors American Express Surpass® Card does not have foreign transaction fees."). The card's
    name must be in the sentence, so a cross-sell line about another card never counts (spot-check round 2, E)."""
    core = _name_core(name)
    if not core:
        return None
    for ln in text.split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+", ln):
            if _NO_FTF.search(sent) and core in _name_core(sent):
                return sent.strip()
    return None


_DEP_RANGE = re.compile(
    r"security\s+deposit\s+of\s+(?P<lo>\$[\d,]+)\s+(?:to|-|–)\s+(?P<hi>\$[\d,]+)"
    r"|minimum\s+(?:security\s+)?deposit\s+of\s+(?P<lo2>\$[\d,]+)\s*\(\s*maximum\s+of\s+(?P<hi2>\$[\d,]+)\s*\)"
    r"|deposit[^.]{0,60}?\bbetween\s+(?P<lo3>\$[\d,]+)\s+and\s+(?P<hi3>\$[\d,]+)"
    r"|\bmaximum\s+(?:security\s+)?deposit\s+(?:of\s+|is\s+)?(?P<hi4>\$[\d,]+)",
    re.IGNORECASE,
)
_DEP_UNCLEAR = re.compile(r"deposit[^.]{0,80}?\bmaximum\s+limit\s+of\s+\$[\d,]+", re.IGNORECASE)


def deposit_range(text: str) -> tuple[int | None, int | None, str | None, str | None]:
    """(min cents, max cents, evidence sentence, note) of a secured card's security deposit: "security deposit of
    $300 to $5,000", "minimum security deposit of $200 (maximum of $5,000)". "depositing more than the minimum
    amount (up to a maximum limit of $1000)" does not say whether the limit is the deposit or the credit line, so it
    is left ambiguous with a note."""
    note = None
    for ln in text.split("\n"):
        for sent in re.split(r"(?<=[.!?])\s+", ln):
            m = _DEP_RANGE.search(sent)
            if m:
                lo = m.group("lo") or m.group("lo2") or m.group("lo3")
                hi = m.group("hi") or m.group("hi2") or m.group("hi3") or m.group("hi4")
                return (parse_money(lo) if lo else None), parse_money(hi), sent.strip(), None
            if note is None and _DEP_UNCLEAR.search(sent):
                note = f"maximum deposit unclear (deposit or credit line?): {sent.strip()[:160]}"
    return None, None, None, note


_NO_OFFER = re.compile(
    r"\b(?:won[’']t|will\s+not|isn[’']t|is\s+not|aren[’']t|are\s+not)\s+(?:be\s+)?eligible\s+for\s+(?:a\s+|the\s+|any\s+)?"
    r"(?:new\s+card\s?member|welcome|sign[- ]?up)\s+(?:bonus|offer)"
    r"|\b(?:this\s+card\s+)?(?:does\s+not|doesn[’']t)\s+(?:offer|have|include)\s+(?:a\s+|any\s+)?"
    r"(?:new\s+card\s?member|welcome|sign[- ]?up)\s+(?:bonus|offer)",
    re.IGNORECASE,
)
_NO_OFFER_CONDITIONAL = re.compile(r"\bif\b|\bmay\b|\bpreviously\b|\bwithin\s+the\s+(?:last|past)\b", re.I)


def no_offer_statement(text: str) -> str | None:
    """A line where the issuer states this card has no welcome offer ("You'll earn the usual Savor ... rewards, but
    won't be eligible for new cardmember bonus cash or 0% intro APR"). Eligibility rules for an existing offer
    ("may not be eligible ... if you previously held this card") are not a statement of absence."""
    for ln in text.split("\n"):
        if _NO_OFFER.search(ln) and not _NO_OFFER_CONDITIONAL.search(ln):
            return ln.strip()
    return None


_END_LINE = re.compile(
    r"\b(?:offer\s+(?:ends|expires|valid\s+through)|ends|expires|apply\s+by|available\s+through|through|until)\b[^.\n]{0,40}?"
    r"(?:(?P<mon>january|february|march|april|may|june|july|august|september|october|november|december)\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})"
    r"|(?P<nm>\d{1,2})/(?P<nd>\d{1,2})/(?P<ny>\d{2}(?:\d{2})?))",
    re.IGNORECASE,
)


def offer_end(text: str, block: str) -> tuple[date, str] | None:
    """An end date stated for this offer: in the block, or on a line that repeats the offer's amount ("Earn 100,000
    points ... Offer ends 7/29/26"). Returns (date, the line it came from)."""
    m = _AMOUNT_TOKEN.search(block)
    cands = [block] + ([ln for ln in text.split("\n") if m.group(0) in ln] if m else [])
    # a single standalone "Offer expires 01/27/2027." on the page (deposit offer pages)
    alone = [ln for ln in text.split("\n") if re.match(r"^\s*offer\s+(?:expires|ends)\b", ln, re.I)]
    if len({ln.strip() for ln in alone}) == 1:
        cands.append(alone[0])
    for ln in cands:
        e = _END_LINE.search(ln)
        if not e:
            continue
        if e.group("mon"):
            d = date(int(e.group("y")), _MONTHS[e.group("mon").lower()], int(e.group("d")))
        else:
            y = int(e.group("ny"))
            d = date(y + 2000 if y < 100 else y, int(e.group("nm")), int(e.group("nd")))
        return d, ln
    return None


def offer_context(text: str, block: str) -> str:
    """Lines elsewhere on the page that complete an offer headline lacking its requirement: the "Earn ... / Plus,
    earn ..." lines right after another occurrence of the headline amount (tiers), and footnotes that repeat the
    amount with a spending requirement ("$750 cash back will be awarded if ... Net Purchases totaling $6,000 ...")."""
    m = _AMOUNT_TOKEN.search(block)
    if not m:
        return ""
    amt = m.group(0)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    nb = norm_ws(block)
    extra: list[str] = []
    for i, ln in enumerate(lines):
        if amt not in ln:
            continue
        if _SPEND_PHRASE.search(ln) and norm_ws(ln) not in nb:
            extra.append(ln)
        for nxt in lines[i + 1 : i + 4]:
            if (_FOLLOW.search(nxt) and _SPEND_PHRASE.search(nxt)) or re.match(
                r"^plus,?\s+earn\b", nxt, re.I
            ):
                extra.append(nxt)
            elif re.match(r"^the\s+[\d,]+\s+(?:PQP|Premier qualifying points)\s+are\b", nxt, re.I):
                continue  # "The 2,000 PQP are in addition to ...": an explanation between two tiers
            elif not _FOLLOW.search(nxt):
                break
    seen: list[str] = []
    for e in extra:
        if norm_ws(e) not in nb and e not in seen:
            seen.append(e)
    return " ".join(seen[:4])


def _numeric_date(m: re.Match[str] | None) -> date | None:
    if not m:
        return None
    y = int(m.group(3))
    return date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))


def _d(m: re.Match[str] | None) -> date | None:
    if not m:
        return None
    return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))


# ----------------------------------------------------------------------------------------------- deposit accounts


def monthly_fee(doc: PageDoc, ctx: ExtractionContext) -> Sourced[Any]:
    lab = labelled(doc, "monthly_fee")
    if lab is None:
        line = first_line(
            doc,
            r"\b(?:no monthly (?:maintenance |service )?fees?|\$\d+(?:\.\d\d)?\s+monthly "
            r"(?:maintenance |service )?fee)",
        )
        lab = (line, line, "free_text") if line else None
    if lab is None:
        return ctx.field(None, None)
    amt = parse_money(lab[0])
    return ctx.field(amt, lab[1], method=lab[2]) if amt is not None else placeholder_or_missing(ctx, lab[0])


def fee_waivers(statements: Iterable[str], ctx: ExtractionContext) -> Sourced[list[FeeWaiver]]:
    waivers: list[FeeWaiver] = []
    evid: list[str] = []
    for st in statements:
        low = st.lower()
        amt = parse_money(st)
        kind: str | None = None
        age_max = age_min = None
        if re.search(r"(?:direct|electronic)\s+deposits?", low) and amt:
            kind = "direct_deposit_total" if "direct" in low else "electronic_deposit_total"
        elif re.search(r"average\s+(?:daily\s+|monthly\s+)?(?:ledger\s+)?balance", low) and amt:
            kind = "min_avg_balance"
        elif re.search(r"(?:minimum\s+)?daily\s+balance|balance of", low) and amt:
            kind = "min_daily_balance"
        elif re.search(r"\blinked\b|\brelationship\b", low):
            kind = "linked_account"
        elif m := re.search(
            r"under (?:the )?age (?:of )?(\d{2})|(?:age|ages)\s+(\d{2})\s*(?:-|to|through)\s*(\d{2})|"
            r"(\d{2}) (?:years|or older|and older)",
            low,
        ):
            kind = "age"
            if m.group(1):
                age_max = int(m.group(1)) - 1
            elif m.group(2):
                age_min, age_max = int(m.group(2)), int(m.group(3))
            elif m.group(4):
                age_min = int(m.group(4))
        elif "student" in low:
            kind = "student"
        if kind:
            period = (
                "monthly"
                if re.search(r"\b(?:each|per|every)\s+(?:monthly\s+)?(?:statement|month)", low)
                else None
            )
            waivers.append(
                FeeWaiver(
                    kind=kind,
                    amount_cents=amt if kind not in {"linked_account", "age", "student"} else None,
                    age_max=age_max,
                    age_min=age_min,
                    period=period,
                    text=st,
                )
            )
            evid.append(st)
    if not waivers:
        return ctx.field(None, None)
    s = ctx.field(waivers, evid[0], method="free_text", name="fee_waivers")
    for e in evid[1:]:
        if ctx.locate(e) is None:
            return ctx.field(None, None, null_reason=NullReason.ambiguous)
    return s


def apy_value(doc: PageDoc, ctx: ExtractionContext) -> Sourced[Any]:
    lab = labelled(doc, "apy")
    if lab is None:
        line = first_line(
            doc, r"\d+(?:\.\d+)?%\s*(?:annual percentage yield|apy)|apy[^.\n]{0,30}(?:nan|--|\$|%)"
        )
        lab = (line, line, "free_text") if line else None
    if lab is None:
        return ctx.field(None, None)
    if contains_placeholder(lab[0]) or re.search(r"\bNaN\b", lab[0]):
        return ctx.field(None, None, null_reason=NullReason.requires_render)
    v = parse_percent(lab[0])
    return ctx.field(v, lab[1], method=lab[2]) if v is not None else placeholder_or_missing(ctx, lab[0])


def apy_tiers(doc: PageDoc, ctx: ExtractionContext, css: str = "table.apy-tiers tr") -> Sourced[Any]:
    tiers: list[ApyTier] = []
    first: str | None = None
    for lab, val in table_rows(doc, css):
        if contains_placeholder(val):
            return ctx.field(None, None, null_reason=NullReason.requires_render)
        amounts = find_amounts(lab)
        apy = parse_percent(val)
        if apy is None or not amounts:
            continue
        lo = amounts[0].cents
        hi = amounts[1].cents if len(amounts) > 1 else None
        if re.search(r"\b(?:less than|under|below|up to)\b", lab, re.IGNORECASE) and len(amounts) == 1:
            lo, hi = 0, amounts[0].cents
        tiers.append(ApyTier(min_balance_cents=lo, max_balance_cents=hi, apy_pct=apy))
        first = first or val
    if not tiers:
        return ctx.field(None, None)
    return ctx.field(
        sorted(tiers, key=lambda t: t.min_balance_cents), first, method="table_cell", name="apy_tiers"
    )


def states(text: str, ctx: ExtractionContext) -> Sourced[Any]:
    m = re.search(
        r"(?i:available (?:only )?(?:to residents of|in)(?: the following states)?|offered in)[:\s]+"
        r"((?:[A-Z]{2}(?:,\s*|\s+and\s+|\s+))+[A-Z]{2})",
        text,
    )
    if not m:
        return ctx.field(None, None)
    found = [s for s in re.findall(r"\b[A-Z]{2}\b", m.group(1)) if s in US_STATES]
    return ctx.field(found or None, m.group(0), method="free_text", name="eligible_states")


def withdrawal_limit(doc: PageDoc, ctx: ExtractionContext) -> tuple[Sourced[Any], Sourced[Any]]:
    line = first_line(
        doc,
        r"(?:limit(?:ed)? (?:of|to)|up to)\s+(\d+|six)\s+(?:\w+\s+)?withdrawals|withdrawal"
        r" (?:limit|restriction)",
    )
    if not line:
        return ctx.field(None, None), ctx.field(None, None)
    m = re.search(r"(\d+|six)\s+(?:\w+\s+)?withdrawals", line, re.IGNORECASE)
    n = (6 if m and m.group(1).lower() == "six" else int(m.group(1))) if m else None
    return ctx.field(line, line, method="free_text"), ctx.field(n, line, method="free_text")


def min_amount(doc: PageDoc, ctx: ExtractionContext, key: str) -> Sourced[Any]:
    lab = labelled(doc, key)
    if lab is None and key == "min_opening":
        line = first_line(
            doc,
            r"(?:\$\d[\d,]*|no minimum)\s+(?:minimum\s+)?(?:opening\s+)?deposit|"
            r"(?:\$\d[\d,]*|no minimum (?:deposit )?)to open",
        )
        lab = (line, line, "free_text") if line else None
    if lab is None:
        return ctx.field(None, None)
    if re.search(r"\bno minimum\b|\bnone\b|\$0\b", lab[0], re.IGNORECASE):
        return ctx.field(0, lab[1], method=lab[2])
    amt = parse_money(lab[0])
    return ctx.field(amt, lab[1], method=lab[2]) if amt is not None else placeholder_or_missing(ctx, lab[0])
