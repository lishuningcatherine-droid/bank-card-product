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
    RewardRateRec,
    Sourced,
)
from bankrec.parsers.money import find_amounts, parse_fee_schedule, parse_money
from bankrec.parsers.offers import Qualifier, parse_offer_block
from bankrec.parsers.percent import parse_percent, parse_percent_range
from bankrec.parsers.period import parse_period
from bankrec.parsers.placeholders import contains_placeholder, is_placeholder
from bankrec.parsers.rewards import _MONTHS, parse_reward_statement

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
                months = (p.months if p else None) or (
                    12 if sched.intro_text and "first year" in sched.intro_text else None
                )
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
    r"(?<![\w$.,])\d{1,2}(?:\.\d{1,2})?\s*(?:%|[xX]\b|\s+(?:points?|miles?|avios)\s+(?:per|for\s+(?:each|every))\b)"
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
    for st in statements:
        rr = parse_reward_statement(st)
        if rr is None:
            continue
        for cat in rr.categories:
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
            )
            out.append(ctx.field(rec, st, method="free_text", name=f"reward:{cat}"))
    return [s for s in out if s.present]


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
                )
            )
            # A headline without its own requirement/window inherits them from the explicit tiers.
            if po.requirement_type is None:
                po.requirement_type = tp.requirement_type
            if po.window is None and tp.window is not None:
                po.window, po.window_text = tp.window, tp.window_text
            if po.required_dd_count is None:
                po.required_dd_count = tp.required_dd_count
    window_days = window_months = None
    if po.window is not None:
        if po.window.unit == "days":
            window_days = po.window.value
        else:
            window_months = po.window.months
            window_days = po.window.days
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
            qualification_window_days=window_days,
            qualification_window_months=window_months,
            qualification_window_text=po.window_text,
            holding_period_days=po.holding.days if po.holding else None,
            expiration_date=_d(exp) or _numeric_date(exp_numeric),
            open_by_date=_d(open_by),
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
    r"(?:^|[.*†!]\s*|\bplus,?\s+|\band\s+)(?:earn|get)\s+(?:an?\s+)?(?P<add>additional\s+|another\s+)?"
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
        days = None
        end = block.find(".", m.end())
        w = re.search(
            r"(?:within|in)\s+(?:the\s+|your\s+)?(?:first\s+)?(\d+)\s*(days?|months?)",
            block[m.start() : end if end != -1 else len(block)],
            re.IGNORECASE,
        )
        if w:
            n = int(w.group(1))
            days = n if w.group(2).lower().startswith("day") else n * 30
        out.append(
            OfferTier(
                amount=amt,
                requirement_min_cents=int(m.group("req").replace(",", "")) * 100,
                text=m.group(0).strip(),
                window_days=days,
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
