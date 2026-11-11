"""Personal check of current offer campaigns (DESIGN §27.10).

For each campaign the visitor gets six separate judgements — never one combined score:

1. offer appeal       — the offer itself, against the history this site recorded
2. personal fit       — the card's everyday earning and fee against the visitor's spending and preferences
3. reaching the spend — natural monthly spend × the window vs. the requirement, with a 20% safety margin
4. known eligibility  — each issuer or community rule checked against the answers, with its source type
5. uncertainty        — what is missing and what rests only on community reports
6. suggested action   — consider now / confirm first / improve credit first / not a fit for now

Approval ("can you be approved") and bonus eligibility ("can you earn this offer") are shown apart. The site never
estimates approval odds, never treats a score alone as decisive, and never fills a missing answer in the visitor's
favour. A known conflict is listed first and is never outweighed by a large reward.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from bankrec.recommend.cards import annual_rewards
from bankrec.recommend.common import usd
from bankrec.recommend.models import CardRequest
from bankrec.tracker import config
from bankrec.tracker.profile import MatchProfile
from bankrec.tracker.rules import BANK_NAME, CardFacts, Finding, evaluate

Action = Literal["consider_now", "verify_first", "improve_credit", "not_suitable"]
ACTION_LABEL: dict[str, str] = {
    "consider_now": "You could consider it now",
    "verify_first": "Confirm the conditions first",
    "improve_credit": "Improve your credit first",
    "not_suitable": "Not a fit for now",
}
ACTION_ORDER = {"consider_now": 0, "verify_first": 1, "improve_credit": 2, "not_suitable": 3}
OUTCOME_LABEL = {
    "conflict": "Conflict",
    "needs_verification": "Needs verification",
    "possible_conflict": "Possible conflict",
    "unknown": "Needs your answer",
    "clear": "No conflict found",
    "info": "Information",
}
BASIS_LABEL = {
    "official": "Issuer's published rule",
    "community": "Community-reported rule (not published by the issuer)",
}


def basis_label(r: dict[str, Any]) -> str:
    """Official rules say whether this site read them on the issuer's page; community rules say how established
    they are. Every community label says it is a community-reported rule (owner 2026-11-10)."""
    if r["source_type"] == "community":
        if r.get("confidence") == "strong":
            return "Community-reported rule, widely corroborated (not published by the issuer)"
        return "Community-reported rule, less established (not published by the issuer)"
    if r.get("verification") == "third_party_quote":
        return "Issuer's rule as quoted by a third party — not officially verified"
    return "Issuer's published rule"


HISTORY_LABEL = {
    "none": "no credit history",
    "lt_1y": "less than 1 year of credit history",
    "1_2y": "1–2 years of credit history",
    "2_5y": "2–5 years of credit history",
    "5y_plus": "more than 5 years of credit history",
}
INCOME_LABEL = {
    "none": "no income",
    "lt_25k": "under $25,000",
    "25k_50k": "$25,000–$50,000",
    "50k_100k": "$50,000–$100,000",
    "100k_150k": "$100,000–$150,000",
    "150k_plus": "over $150,000",
}
INCOME_TOP = {"none": 0, "lt_25k": 25_000, "25k_50k": 50_000, "50k_100k": 100_000, "100k_150k": 150_000}


def income_notes(p: MatchProfile) -> tuple[list[str], list[str]]:
    """(approval points, things to confirm). Income is optional; no minimum income is published for these cards."""
    inc = p.annual_income
    points: list[str] = []
    confirm: list[str] = []
    if inc in (None, "prefer_not"):
        return points, confirm
    if inc == "none":
        points.append(
            "You said you have no income. Card issuers must consider your ability to pay from income or assets"
            " you can access (Regulation Z, 12 CFR 1026.51); without it, approval is a real risk."
        )
        confirm.append("Income or assets you can access: issuers must check your ability to pay.")
    else:
        points.append(
            f"You gave a yearly income of {INCOME_LABEL[inc]}. Issuers weigh income with your existing credit lines;"
            " they publish no minimum income for these cards."
        )
    if p.student:
        points.append(
            "If you are under 21, the same rule requires income or assets of your own, or an applicant aged 21 or"
            " over who is also liable (12 CFR 1026.51(b))."
        )
    monthly = p.natural_monthly_spend()
    top = INCOME_TOP.get(inc)
    if monthly is not None and top is not None and monthly * 12 > top:
        confirm.append(
            f"Your card spending of {usd(monthly * 100)} a month ({usd(monthly * 1200)} a year) is above the income"
            f" range you gave ({INCOME_LABEL[inc]}); check both figures. Only spend what you can pay in full."
        )
    return points, confirm


# FICO's published score ranges (config/tracker/settings.yaml credit_ranges); used only as a risk signal together
# with other answers, never as a cut-off for any card.
DISCLAIMER = (
    "Information only, not financial advice. The issuer's own terms and decision always prevail; this site cannot"
    " predict approval."
)


class FindingView(BaseModel):
    rule_key: str
    name: str
    effect: Literal["approval", "bonus"]
    basis: Literal["official", "community"]
    basis_label: str
    verification: str
    officially_verified: bool = Field(description="official rule read by this site on the issuer's own page")
    confidence: Literal["strong", "weak"] | None = Field(None, description="community rules only")
    boundary: bool = Field(
        False, description="unknown only because an answer falls in the window's boundary month"
    )
    outcome: Literal["conflict", "needs_verification", "possible_conflict", "unknown", "clear", "info"]
    outcome_label: str
    explanation: str
    needs: list[str]
    excerpt: str
    source_url: str
    source_title: str | None
    verified_at: date


class Judgement(BaseModel):
    status: str
    label: str
    points: list[str] = Field(default_factory=list)


class TierReach(BaseModel):
    spend_cents: int | None
    reward: str
    status: Literal["sufficient", "tight", "insufficient", "unknown"]


class Reach(BaseModel):
    status: Literal["sufficient", "tight", "insufficient", "unknown", "not_required"]
    label: str
    required_cents: int | None
    needed_with_margin_cents: int | None
    window: str | None
    projected_cents: int | None
    text: str
    tiers: list[TierReach] = Field(default_factory=list)


class FirstYear(BaseModel):
    reward_cents: int | None
    first_year_fee_cents: int | None
    net_cents: int | None
    depends_on_points_value: bool
    text: str


class Assessment(BaseModel):
    kind: Literal["offer", "card"] = Field(
        "offer", description="card = a tracked card with no current offer: approval and fit only"
    )
    campaign_id: str | None
    product_id: str | None = None
    card_key: str
    card_name: str
    bank_name: str
    starter: Literal["student", "secured"] | None = None
    action: Action
    action_label: str
    action_reasons: list[str]
    conflicts: list[FindingView] = Field(description="known conflicts, listed before anything else")
    approval: Judgement
    bonus: Judgement
    offer_appeal: Judgement
    personal_fit: Judgement
    reach: Reach
    eligibility: list[FindingView]
    uncertainty: list[str]
    first_year: FirstYear


class Question(BaseModel):
    key: str
    text: str
    why: str


class MatchResponse(BaseModel):
    items: list[Assessment]
    questions: list[Question]
    assumptions: list[str]
    disclaimer: str = DISCLAIMER


# ------------------------------------------------------------------------------------------------ helpers


def rule_dict(r: Any) -> dict[str, Any]:
    """A prod.application_rules row as the dict the checks read."""
    return {
        "rule_key": r.rule_key,
        "bank_id": r.bank_id,
        "name": r.name,
        "rule_type": r.rule_type,
        "source_type": r.source_type,
        "verification": r.verification,
        "effect": r.effect,
        "strength": r.strength,
        "test": r.test,
        "window_months": r.window_months,
        "limit": r.limit_count,
        "counts": r.counts,
        "scope": r.scope or {},
        "source_url": r.source_url,
        "source_title": r.source_title,
        "excerpt": r.excerpt,
        "notes": list(r.notes or []),
        "verified_at": r.verified_at,
        "confidence": r.confidence,
    }


def applies(rule: dict[str, Any], card: CardFacts) -> bool:
    a = (rule.get("scope") or {}).get("applies_to") or rule.get("applies_to") or {}
    if "cards" in a:
        return card.card_key in a["cards"]
    if a.get("bank_id") != card.bank_id:
        return False
    return not (a.get("segment") and a["segment"] != card.segment)


def finding_view(f: Finding) -> FindingView:
    r = f.rule
    vat = r["verified_at"]
    return FindingView(
        rule_key=r["rule_key"],
        name=r["name"],
        effect=r["effect"],
        basis=r["source_type"],
        basis_label=basis_label(r),
        verification=r["verification"],
        officially_verified=r["source_type"] == "official" and r["verification"] == "page_captured",
        confidence=r.get("confidence"),
        boundary=f.boundary,
        outcome=f.outcome,
        outcome_label="Needs checking (boundary month)" if f.boundary else OUTCOME_LABEL[f.outcome],
        explanation=f.explanation,
        needs=f.needs,
        excerpt=r["excerpt"],
        source_url=r["source_url"],
        source_title=r.get("source_title"),
        verified_at=vat if isinstance(vat, date) else date.fromisoformat(str(vat)),
    )


def _window_text(count: int | None, unit: str | None, start: str | None) -> str | None:
    if not count or not unit:
        return None
    starts = {
        "account_opening": " from account opening",
        "card_membership": " of card membership",
        "approval": " from approval",
    }
    u = unit if count != 1 else unit.rstrip("s")
    return f"{count} {u}{starts.get(start or '', ' (start point not stated)')}"


def _spend_over(monthly_dollars: int, count: int, unit: str) -> int | None:
    """Natural spend over a window, in cents. Days are counted as 31 per month (never rounded up)."""
    if unit.startswith("month"):
        return monthly_dollars * 100 * count
    if unit.startswith("day"):
        return math.floor(monthly_dollars * 100 * count / 31)
    if unit.startswith("year"):
        return monthly_dollars * 100 * 12 * count
    return None


def reach(terms: Any, p: MatchProfile, margin: float) -> Reach:
    req = terms.min_spend_cents
    win = _window_text(terms.window_count, terms.window_unit, terms.window_start)
    monthly = p.natural_monthly_spend()
    if req is None or req == 0:
        return Reach(status="not_required", label="No spending requirement stated", required_cents=req,
                     needed_with_margin_cents=None, window=win, projected_cents=None,
                     text="The offer states no spending requirement.")  # fmt: skip
    need = math.ceil(req * (1 + margin))
    base = dict(required_cents=req, needed_with_margin_cents=need, window=win)
    if terms.window_count is None or terms.window_unit is None:
        return Reach(status="unknown", label="Window not stated", projected_cents=None,
                     text=f"Spend {usd(req)}, but the offer text read by this site does not state the time"
                     " allowed; check the issuer's terms.", **base)  # fmt: skip
    if monthly is None:
        return Reach(status="unknown", label="Tell us your monthly spending", projected_cents=None,
                     text=f"Spend {usd(req)} in {win}. Tell us your normal monthly card spending to check this.",
                     **base)  # fmt: skip
    proj = _spend_over(monthly, int(terms.window_count), str(terms.window_unit))
    if proj is None:
        return Reach(status="unknown", label="Window unit not understood", projected_cents=None,
                     text=f"Spend {usd(req)} in {win}.", **base)  # fmt: skip

    def grade(amount: int) -> Literal["sufficient", "tight", "insufficient"]:
        return (
            "sufficient"
            if proj >= math.ceil(amount * (1 + margin))
            else "tight"
            if proj >= amount
            else "insufficient"
        )

    status = grade(req)
    head = (
        f"Your normal spending of {usd(monthly * 100)} a month gives about {usd(proj)} in {win};"
        f" the offer needs {usd(req)} ({usd(need)} with a {int(margin * 100)}% safety margin)."
    )
    tail = {
        "sufficient": " You can likely reach it with spending you already do.",
        "tight": " That is enough only without a safety margin: a slow month or a returned purchase could miss it.",
        "insufficient": " Your normal spending would not reach it. Do not buy things you don't need or use"
        " gift cards, money orders or other ways to create spending to qualify.",
    }[status]
    tiers = []
    if len(terms.tiers or []) > 1:
        for t in terms.tiers:
            amt = t.amount
            reward = f"{amt:,} {t.unit}" if amt is not None and t.unit in ("points", "miles") else (
                usd(amt) if amt is not None else "amount not stated")  # fmt: skip
            tiers.append(
                TierReach(
                    spend_cents=t.spend_cents,
                    reward=reward,
                    status=grade(t.spend_cents) if t.spend_cents is not None else "unknown",
                )
            )
    label = {
        "sufficient": "Reachable with your normal spending",
        "tight": "Reachable only without a safety margin",
        "insufficient": "Not reachable with your normal spending",
    }[status]
    return Reach(status=status, label=label, projected_cents=proj, text=head + tail, tiers=tiers, **base)


def _reward_text(terms: Any) -> str:
    amt, unit = terms.total_amount, terms.unit
    if amt is None:
        return "a reward whose amount was not read"
    text = (
        f"{amt:,} {terms.unit_name or unit}"
        if unit in ("points", "miles")
        else usd(amt) + (" statement credit" if unit == "statement_credit" else "")
    )
    if terms.amount_qualifier == "up_to":
        floor = (
            f"; published minimum {terms.guaranteed_min:,}"
            if terms.guaranteed_min is not None
            else "; no guaranteed minimum published"
        )
        return f"up to {text} (varies by applicant{floor})"
    if terms.amount_qualifier == "starting_at":
        return f"at least {text}"
    return text


def component_text(c: Any) -> str:
    when = f", {c.expires}" if c.expires else ""
    return f"{usd(c.amount_cents)} credit for {c.restriction}{when} — restricted, not cash and not converted to points"


def first_year(v: Any) -> FirstYear:
    fy = _first_year(v)
    comps = list(getattr(v.terms, "offer_components", None) or [])
    if comps:
        fy.text += " Not counted above: " + "; ".join(component_text(c) for c in comps) + "."
    return fy


def offer_appeal(v: Any) -> Judgement:
    h = v.history
    pts = [f"Offer: {_reward_text(v.terms)}" + (f" after spending {usd(v.terms.min_spend_cents)}"
           if v.terms.min_spend_cents else "") + "."]  # fmt: skip
    for comp in getattr(v.terms, "offer_components", None) or []:
        pts.append("Plus a separate component: " + component_text(comp) + ".")
    pts.append(h.text)
    if v.value.cents is not None:
        pts.append(
            f"Worth about {usd(v.value.cents)}"
            + (f" — {v.value.assumption}" if v.value.assumption else "")
            + "."
        )
    elif v.value.assumption:
        pts.append(v.value.assumption + ".")
    pts.append(f"Deadline: {v.deadline_label}.")
    if v.status in ("stale", "pending_verification"):
        pts.append(
            f"Status: {v.status_label} — {v.status_reason or 'the offer could not be re-confirmed recently'}."
        )
    if v.channel != "public":
        pts.append(f"Channel: {v.channel_label}. It is not open to everyone; check you received it.")
    status = h.code if h.code != "insufficient_history" else "no_comparison"
    label = {
        "all_time_high": "Highest recorded on this site",
        "above_usual": "Better than the usual level recorded here",
        "recent_high": "Higher than usual recently",
        "usual": "The usual level recorded here",
        "below_usual": "Below the usual level recorded here",
        "no_comparison": "Not enough history to compare",
        "variable_offer": "Variable offer: not compared with history",
    }[status]
    return Judgement(status=status, label=label, points=pts)


def personal_fit(
    v: Any, p: MatchProfile, product: Any | None, now: Any, overrides: dict[str, float]
) -> Judgement:
    pts: list[str] = []
    bad = False
    unknown = False
    card = v.card
    fee = card.annual_fee_cents
    if p.max_annual_fee is None:
        unknown = True
        pts.append("Tell us the most you would pay in annual fees to check the fee.")
    elif fee is None:
        unknown = True
        pts.append("The card's annual fee was not read; check the issuer's page.")
    else:
        fy = card.first_year_fee_cents
        if fee > p.max_annual_fee * 100:
            bad = True
            first = f" ({usd(fy)} the first year)" if fy is not None and fy != fee else ""
            pts.append(
                f"Annual fee {usd(fee)}{first} is above the {usd(p.max_annual_fee * 100)} you would pay."
            )
        else:
            pts.append(f"Annual fee {usd(fee)} is within the {usd(p.max_annual_fee * 100)} you would pay.")
    if card.segment == "business":
        if p.business_income == "no":
            bad = True
            pts.append(
                "This is a business card; you said you have no business or self-employment income. The"
                " application asks about your business."
            )
        elif p.business_income == "yes":
            pts.append(
                "Business card: you said you have business or side income. A sole proprietor can usually apply"
                " with their own SSN (this site never asks for it)."
            )
        else:
            unknown = True
            pts.append("Business card: tell us whether you have business or side income.")
    pref = p.reward_preference
    is_cash = v.terms.unit in ("cash", "statement_credit") and card.points_program is None
    if pref == "cashback" and not is_cash:
        bad = True
        pts.append(f"Rewards are {card.points_program_name or 'points or miles'}; you prefer cash back.")
    elif pref == "points" and is_cash:
        pts.append("Rewards are cash back; you prefer points or miles.")
    elif pref in ("cashback", "points"):
        pts.append("Reward type matches your preference.")
    if product is not None and p.spend_categories is not None and p.spend_categories.total > 0:
        prog = card.points_program
        cpp: float | None = overrides.get(prog or "")
        if cpp is None and prog:
            cpp = (config.programs().get(prog) or {}).get("floor_cents")
        req = CardRequest(product_type="credit_card", goal="cashback", monthly_spend=p.spend_categories)
        cash_card = product.details.get("reward_currency") == "cashback"
        cents, per_cat, share, _ = annual_rewards(
            product, req, Decimal(str(cpp if cpp is not None else 1)), now
        )
        top = [k.replace("_", " ") for k, x in sorted(per_cat.items(), key=lambda kv: -kv[1])
               if x > 0 and k != "everything_else"][:3]  # fmt: skip
        if cash_card or cpp is not None:
            basis = (
                "" if cash_card or cpp is None else f" (counting 1 point = ${cpp / 100:.4f}".rstrip("0") + ")"
            )
            pts.append(f"Everyday earning on your spending: about {usd(cents)} a year{basis}.")
        else:
            pts.append(f"Everyday earning on your spending: about {cents:,} {card.points_program_name or 'points'}"
                       " a year (no dollar value: no official cash value for these points).")  # fmt: skip
        if top:
            pts.append(f"Bonus rates apply to your {', '.join(top)} spending ({round(share * 100)}% of it).")
        else:
            pts.append("None of your spending categories earns a bonus rate on this card.")
    elif p.spend_categories is None:
        unknown = True
        pts.append("Add your spending by category to compare the card's everyday earning.")
    status, label = (
        ("poor", "Weak fit")
        if bad
        else ("unknown", "Partly checked")
        if unknown
        else ("good", "Fits your answers")
    )
    return Judgement(status=status, label=label, points=pts)


STARTER_NOTE = {
    "student": "This is a student card, made for people starting to build credit.",
    "secured": "This is a secured card: a refundable deposit backs the credit line, and it is made for people"
    " building or rebuilding credit.",
}


def credit_signals(
    p: MatchProfile, ranges: list[dict[str, Any]], starter: str | None = None
) -> tuple[list[str], list[str], list[str]]:
    """(strong risks, cautions, missing). Never an approval prediction.

    On a starter card a short history is expected, so it is a caution, not a reason to wait; on a secured card the
    same goes for negative marks and a low score. Approval is still the issuer's decision and never called easy."""
    strong, caution, missing = [], [], []
    still = " The issuer still reviews your application; this does not mean approval is easy or likely."
    if p.credit_history is None:
        missing.append("How long your credit history is")
    elif p.credit_history in ("none", "lt_1y"):
        if starter:
            caution.append(f"You have {HISTORY_LABEL[p.credit_history]}. {STARTER_NOTE[starter]}{still}")
        else:
            strong.append(
                f"You have {HISTORY_LABEL[p.credit_history]}. Issuers look at how long and how well you have used"
                " credit; a short history is a real risk for cards with large bonuses."
                " Starter cards (student or secured) are checked separately in your results."
            )
    if p.negative_marks is None:
        missing.append("Whether your credit report shows late payments, collections or a bankruptcy")
    elif p.negative_marks:
        msg = "You said your credit report shows late payments, collections or a bankruptcy."
        (caution if starter == "secured" else strong).append(
            msg + (f" {STARTER_NOTE['secured']}{still}" if starter == "secured" else "")
        )
    if p.credit_score is None:
        caution.append(
            "No credit score given (optional): the check relies on your credit history and report instead."
        )
    elif p.score_model == "fico":
        band = next((r for r in ranges if r["min"] <= p.credit_score <= r["max"]), None)
        if band is not None:
            msg = f"Your FICO score {p.credit_score} is in FICO's “{band['name']}” range ({band['min']}–{band['max']})."
            if band.get("risk") == "high":
                (caution if starter == "secured" else strong).append(
                    msg + " That is a real risk; the score is not the only factor."
                )
            elif band.get("risk") == "medium":
                caution.append(
                    msg
                    + " Some issuers may decline or offer a lower limit; the score is not the only factor."
                )
            else:
                caution.append(msg + " A score alone does not decide approval.")
    else:
        caution.append(
            f"You gave a score of {p.credit_score}"
            + (" without its model" if p.score_model in (None, "unknown") else f" ({p.score_model})")
            + ". Score ranges differ between models and bureaus, and a score alone does not decide approval."
        )
    if p.student:
        caution.append(
            "Being a student does not make approval easier by itself; issuers also consider income you can"
            " access and your credit history."
        )
    return strong, caution, missing


def _first_year(v: Any) -> FirstYear:
    val = v.value
    fee = val.first_year_fee_cents
    if val.cents is None:
        return FirstYear(reward_cents=None, first_year_fee_cents=fee, net_cents=None,
                         depends_on_points_value=val.depends_on_points_value,
                         text=(val.assumption or "No dollar value: the reward amount was not read") + ".")  # fmt: skip
    if fee is None:
        return FirstYear(reward_cents=val.cents, first_year_fee_cents=None, net_cents=None,
                         depends_on_points_value=val.depends_on_points_value,
                         text=f"Reward about {usd(val.cents)}; first-year fee not read, so no net value.")  # fmt: skip
    net = val.cents - fee
    dep = (
        f" The reward part assumes: {val.assumption}."
        if val.depends_on_points_value and val.assumption
        else ""
    )
    return FirstYear(
        reward_cents=val.cents,
        first_year_fee_cents=fee,
        net_cents=net,
        depends_on_points_value=val.depends_on_points_value,
        text=f"First-year value: reward {usd(val.cents)} − first-year fee {usd(fee)} = {usd(net)}.{dep}"
        " Everyday rewards are not included.",
    )


def assess(
    v: Any,
    card: CardFacts,
    facts: dict[str, CardFacts],
    rules: list[dict[str, Any]],
    p: MatchProfile,
    today: date,
    *,
    product: Any | None = None,
    now: Any = None,
    overrides: dict[str, float] | None = None,
) -> Assessment:
    cfg = config.settings()
    margin = float(cfg["reach"]["safety_margin"])
    findings = [evaluate(r, card, facts, p, today) for r in rules if applies(r, card)]
    order = {
        "conflict": 0,
        "needs_verification": 1,
        "possible_conflict": 2,
        "unknown": 3,
        "info": 4,
        "clear": 5,
    }
    findings.sort(key=lambda f: (order[f.outcome], f.effect != "bonus", f.basis != "official"))
    views = [finding_view(f) for f in findings]
    conflicts = [x for x in views if x.outcome == "conflict"]

    strong, caution, missing = credit_signals(
        p, list(cfg.get("credit_ranges") or []), getattr(v.card, "starter", None)
    )
    inc_points, inc_confirm = income_notes(p)
    r = reach(v.terms, p, margin)
    fit = personal_fit(v, p, product, now, overrides or {})

    # approval and bonus judgements, kept apart
    def judge(effect: str) -> Judgement:
        fs = [x for x in views if x.effect == effect]
        pts = [f"{x.outcome_label}: {x.name} ({x.basis_label.lower()}) — {x.explanation}" for x in fs
               if x.outcome in ("conflict", "needs_verification", "possible_conflict", "unknown")]  # fmt: skip
        if any(x.outcome == "conflict" for x in fs):
            st = "known_conflict"
        elif any(x.outcome == "needs_verification" for x in fs):
            st = "needs_verification"
        elif any(x.outcome == "possible_conflict" for x in fs):
            st = "possible_conflict"
        elif any(x.outcome == "unknown" for x in fs):
            st = "needs_info"
        else:
            st = "no_known_conflict"
        if effect == "approval":
            pts += strong + caution + inc_points
            if st == "no_known_conflict" and strong:
                st = "credit_risk"
            if st == "no_known_conflict" and missing:
                st = "needs_info"
            pts.append("Only the issuer decides approval; this site does not estimate approval odds.")
            label = {
                "known_conflict": "A known approval rule blocks this application",
                "needs_verification": "Needs verification: a rule quoted only by a third party may apply",
                "possible_conflict": "A rule may block approval",
                "credit_risk": "No known rule conflict, but your credit history is a risk",
                "needs_info": "Not enough information to judge",
                "no_known_conflict": "No known rule conflict (approval is still the issuer's decision)",
            }[st]
        else:
            if any(x.rule_key == "amex_eligibility_notice" for x in fs):
                pts.append(
                    "American Express says during the application whether you can get the welcome offer;"
                    " if it says you cannot, you can stop before submitting."
                )
            label = {
                "known_conflict": "You are not eligible for this bonus by your answers",
                "needs_verification": "Needs verification: a restriction quoted only by a third party may apply",
                "possible_conflict": "You may not be eligible for this bonus",
                "needs_info": "Bonus eligibility needs your answers",
                "no_known_conflict": "No known bonus restriction applies by your answers",
            }[st]
        return Judgement(status=st, label=label, points=pts)

    approval, bonus = judge("approval"), judge("bonus")

    uncertainty: list[str] = []
    for x in views:
        uncertainty += [n for n in x.needs if n not in uncertainty]
    for m in missing:
        if m not in uncertainty:
            uncertainty.append(m)
    if r.status == "unknown":
        uncertainty.append(r.text)
    for x in views:
        if x.outcome == "needs_verification":
            uncertainty.append(
                f"“{x.name}” matches your answers, but this site has only a third party's quotation of the issuer's"
                " wording; it needs verification against the issuer's own terms before it is treated as a conflict."
            )
    community = [x for x in views if x.basis == "community" and x.outcome != "clear"]
    for x in community:
        uncertainty.append(f"“{x.name}” is a community-reported rule; the issuer does not publish it.")
    if v.status in ("stale", "pending_verification"):
        uncertainty.append(f"The offer itself needs re-confirming: {v.status_label.lower()}.")
    if v.terms.end.date is None:
        uncertainty.append("The issuer has not stated an end date; the offer could change at any time.")
    if p.annual_income in (None, "prefer_not"):
        uncertainty.append(
            "Issuers also consider your income and existing credit lines; you have not given an income range."
        )
    else:
        uncertainty.append(
            "Issuers also consider your existing credit lines, which this check does not ask about."
        )
    uncertainty += inc_confirm

    # suggested action (strictest condition wins)
    reasons: list[str] = []
    official_conflict = [x for x in conflicts if x.basis == "official"]
    community_block = [x for x in conflicts if x.basis == "community" and x.effect == "approval"]
    action: Action
    no_business = card.segment == "business" and p.business_income == "no"
    if official_conflict or community_block or r.status == "insufficient" or no_business:
        action = "not_suitable"
        for x in official_conflict:
            reasons.append(f"{x.name}: {x.explanation} ({x.basis_label})")
        for x in community_block:
            reasons.append(f"{x.name}: {x.explanation} ({x.basis_label})")
        if r.status == "insufficient":
            reasons.append(r.text)
        if no_business:
            reasons.append("Business card, and you said you have no business or side income.")
    elif strong:
        action = "improve_credit"
        reasons += strong
        if r.status in ("tight", "unknown"):
            reasons.append(r.text)
    else:
        blockers: list[str] = list(inc_confirm)
        for x in views:
            if x.outcome in ("needs_verification", "possible_conflict", "unknown", "conflict"):
                blockers.append(f"{x.name}: {x.explanation} ({x.basis_label})")
        if missing:
            blockers.append("Missing: " + "; ".join(m.lower() for m in missing) + ".")
        if r.status in ("tight", "unknown"):
            blockers.append(r.text)
        if card.segment == "business" and p.business_income != "yes":
            blockers.append("Confirm you have business or side income for a business card.")
        if v.status in ("stale", "pending_verification"):
            blockers.append(f"The offer is marked “{v.status_label}”; confirm it on the issuer's page.")
        if v.channel != "public":
            blockers.append(f"{v.channel_label}: only for people who received it.")
        if blockers:
            action = "verify_first"
            reasons += blockers
        else:
            action = "consider_now"
            reasons.append(
                f"No known rule conflict by your answers; {r.text.split(';')[0].lower()} covers the"
                f" {usd(v.terms.min_spend_cents or 0)} requirement with the {int(margin * 100)}% margin."
                if r.status == "sufficient"
                else "No known rule conflict by your answers, and no spending requirement."
            )
            if fit.status == "poor":
                reasons.append(
                    "Note the weak fit: " + "; ".join(x for x in fit.points if "above" in x or "prefer" in x)
                )

    return Assessment(
        campaign_id=v.id,
        product_id=v.card.product_id,
        starter=getattr(v.card, "starter", None),
        card_key=card.card_key,
        card_name=v.card.name,
        bank_name=v.card.bank_name or BANK_NAME.get(card.bank_id, card.bank_id),
        action=action,
        action_label=ACTION_LABEL[action],
        action_reasons=reasons,
        conflicts=conflicts,
        approval=approval,
        bonus=bonus,
        offer_appeal=offer_appeal(v),
        personal_fit=fit,
        reach=r,
        eligibility=views,
        uncertainty=uncertainty,
        first_year=first_year(v),
    )


QUESTIONS: list[tuple[str, str, str]] = [
    (
        "credit_history",
        "How long have you had credit (any card or loan)?",
        "Issuers look at the length of your history.",
    ),
    (
        "monthly_spend",
        "How much do you normally spend on cards each month?",
        "To check whether you can reach the spending requirement without extra spending.",
    ),
    (
        "new_accounts_24m",
        "How many credit cards have you opened in the last 24 months, with any bank? Include authorized-user cards and business cards that appear on your personal credit report.",
        "Chase and other issuers limit how many new cards you can have opened recently.",
    ),
    (
        "cards",
        "Which cards from these banks do you have or have you had, and did you get their bonus?",
        "Many welcome offers exclude people who had the card or its bonus before.",
    ),
    (
        "negative_marks",
        "Does your credit report show late payments, collections or a bankruptcy?",
        "This matters more than the score alone.",
    ),
    (
        "max_annual_fee",
        "What is the most you would pay in annual fees?",
        "To check the card's fee against your limit.",
    ),
    (
        "credit_score",
        "Do you know your credit score and its model (FICO or VantageScore)?",
        "Optional. A score is one signal, never the only one.",
    ),
    ("business_income", "Do you have business or side income?", "Business cards ask about your business."),
]


def questions(p: MatchProfile) -> list[Question]:
    """The next questions worth asking, most decisive first (progressive form)."""
    have = {
        "credit_history": p.credit_history is not None,
        "monthly_spend": p.natural_monthly_spend() is not None,
        "new_accounts_24m": p.new_accounts_24m is not None or p.cards_complete,
        "cards": p.cards_complete or bool(p.cards),
        "negative_marks": p.negative_marks is not None,
        "max_annual_fee": p.max_annual_fee is not None,
        "credit_score": p.credit_score is not None,
        "business_income": p.business_income is not None,
    }
    return [Question(key=k, text=t, why=w) for k, t, w in QUESTIONS if not have[k]][:3]


def assumptions(margin: float) -> list[str]:
    return [
        f"Reaching the spend: your normal monthly spending × the months allowed must exceed the requirement by"
        f" {int(margin * 100)}% (a month of a window in days counts as 31 days). Extra or created spending is never"
        " assumed.",
        "Rules are checked only against your answers. A rule is shown as a conflict only when your answers meet it,"
        " and as clear only when your answers rule it out; otherwise it says what is missing.",
        "Issuer's published rules and community-reported rules are labelled apart. Community rules are not"
        " published by the issuer and may be out of date.",
        "Approval and bonus eligibility are judged separately. This site never estimates approval odds and never"
        " uses a credit score alone.",
        "Your answers are used for this check only: the server does not store or log them.",
    ]


def assess_card(
    card_view: Any,
    card: CardFacts,
    facts: dict[str, CardFacts],
    rules: list[dict[str, Any]],
    p: MatchProfile,
    today: date,
    *,
    product: Any | None = None,
    now: Any = None,
    overrides: dict[str, float] | None = None,
) -> Assessment:
    """A tracked card with no current offer (e.g. a secured or student card): approval rules, credit signals and
    fit only — there is no bonus to qualify for and no spending requirement."""
    from bankrec.tracker import views as TV

    end = TV.moment({"date": None, "time": None, "time_known": False, "confirmed": False})
    assert end is not None
    fee = card_view.annual_fee_cents
    terms = TV.Terms(
        offer_type="other", channel="public", tiers=[], total_amount=None, unit="cash", min_spend_cents=None,
        window_count=None, window_unit=None, window_start="not_stated", annual_fee_cents=fee,
        first_year_fee_cents=card_view.first_year_fee_cents, start=None, end=end, eligibility_text=None,
        verbatim=None, offer_url=card_view.official_url,
    )  # fmt: skip
    v = TV.CampaignView(
        id="", campaign_key=f"{card.card_key}|card", card=card_view, channel="public",
        channel_label="Public application", offer_type="other", offer_type_label="No current offer",
        status="active", status_label="No current offer", status_reason=None, source_kind="official",
        source_label=TV.SOURCE_LABEL["official"], source_name=None, officially_verified=True,
        first_seen_at=now, last_checked_at=None, last_verified_at=None, version=0, terms=terms,
        deadline_label="No current offer", countdown_to=None,
        value=TV.Value(cents=None, depends_on_points_value=False, assumption=None, cents_per_point=None,
                       first_year_net_cents=None, first_year_fee_cents=card_view.first_year_fee_cents),
        history=TV.HistoryLabel(code="insufficient_history", text="", records=0, coverage_months=0, median=None,
                                official_only=False),
        demo=card_view.demo,
    )  # fmt: skip
    approval_rules = [r for r in rules if r["effect"] == "approval"]
    a = assess(v, card, facts, approval_rules, p, today, product=product, now=now, overrides=overrides)
    a.kind, a.campaign_id, a.product_id, a.starter = "card", None, card_view.product_id, card_view.starter
    a.offer_appeal = Judgement(
        status="no_offer",
        label="No current welcome offer tracked",
        points=["This site has no current welcome offer recorded for this card."]
        + (
            [
                "A secured card asks for a refundable security deposit that usually sets your credit line;"
                " check the deposit terms on the issuer's page."
            ]
            if card_view.starter == "secured"
            else []
        ),
    )
    a.bonus = Judgement(status="no_offer", label="No offer to qualify for", points=[])
    fee_text = usd(fee) if fee is not None else "not read"
    a.first_year = FirstYear(
        reward_cents=None, first_year_fee_cents=card_view.first_year_fee_cents, net_cents=None,
        depends_on_points_value=False, text=f"No welcome offer; annual fee {fee_text}. Everyday rewards are not included.",
    )  # fmt: skip
    a.uncertainty = [u for u in a.uncertainty if "end date" not in u]
    return a


def run(
    session: Any,
    req: Any,
    now: Any,
    *,
    allow_demo: bool,
    products: dict[str, Any] | None = None,
) -> MatchResponse:
    """Check the requested (or every current) campaign against the visitor's profile. Nothing is stored."""
    from sqlalchemy import select

    from bankrec.db import prod as P
    from bankrec.tracker import views as TV

    p: MatchProfile = req.profile
    today = p.as_of or now.date()
    b = TV.Builder(session, allow_demo=allow_demo, overrides=dict(req.point_values))
    facts: dict[str, CardFacts] = {}
    for key in b._cards:
        s = b.card(key)
        rp = (s.reports_to_personal_credit or {}).get("value")
        facts[key] = CardFacts(
            card_key=key,
            bank_id=s.bank_id,
            segment=s.segment,
            name=s.name,
            series=s.series,
            reports_personal=rp,
            annual_fee_cents=s.annual_fee_cents,
        )
    rules = [rule_dict(r) for r in session.scalars(select(P.ApplicationRule))]
    wanted = set(req.campaign_ids or [])
    items = []
    for c in b.campaigns():
        if wanted and str(c.id) not in wanted:
            continue
        v = b.view(c, now)
        if not wanted and v.status not in TV.CURRENT:
            continue
        prod = (products or {}).get(v.card.product_id or "")
        items.append(
            assess(
                v,
                facts[c.card_key],
                facts,
                rules,
                p,
                today,
                product=prod,
                now=now,
                overrides=dict(req.point_values),
            )
        )
    if not wanted:
        # tracked cards with no current offer (starter cards among them) are checked too, without a bonus part
        with_offer = {a.card_key for a in items}
        for key, row in b._cards.items():
            if key in with_offer or (row.demo and not allow_demo):
                continue
            cv = b.card(key)
            prod = (products or {}).get(cv.product_id or "")
            items.append(
                assess_card(
                    cv,
                    facts[key],
                    facts,
                    rules,
                    p,
                    today,
                    product=prod,
                    now=now,
                    overrides=dict(req.point_values),
                )
            )
    items.sort(key=lambda a: (ACTION_ORDER[a.action], a.kind != "offer", a.bank_name, a.card_name))
    margin = float(config.settings()["reach"]["safety_margin"])
    return MatchResponse(items=items, questions=questions(p), assumptions=assumptions(margin))
