"""Credit-card engine (brief §11.2). Deterministic; every number is explainable."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bankrec.recommend.common import (
    DISCLAIMER,
    clip,
    completeness,
    components,
    eligible_offers,
    minmax,
    period_months,
    usd,
    window_months,
    worst_case_requirement,
)
from bankrec.recommend.config import cents_per_point, scoring
from bankrec.recommend.models import (
    Achievability,
    CardRequest,
    Excluded,
    OfferView,
    ProductView,
    RateView,
    Reason,
    RecommendResponse,
    Result,
    Values,
)

PROFILE_RANK = {"limited": 1, "fair": 2, "good": 3, "excellent": 4}
PERIODS = {"monthly": 12, "quarterly": 4, "annual": 1}
TRAVEL_BENEFITS = {"travel", "airline", "hotel"}
NO_REWARDS_GOALS = {
    "low_interest",
    "balance_transfer",
    "build_credit",
}  # rewards_program == "none" (DESIGN §24.15)
PERIOD_NOUN = {"monthly": "month", "quarterly": "quarter", "annual": "year"}


def _r(rate: Decimal, unit: str) -> str:
    """Human rate text: Decimal("2.0000") → "2%" (or "2x")."""
    n = rate.normalize()
    return f"{n:f}{'%' if unit == 'pct' else 'x'}"


@dataclass
class CardCalc:
    p: ProductView
    rewards_cents: int
    credits_cents: int
    credits_counted: list[dict[str, Any]]
    annual_fee_cents: int
    first_year_fee_cents: int
    fee_y2_cents: int
    fee_y3_cents: int
    promo_cents: int
    offer: OfferView | None
    possible: OfferView | None
    achievability: Achievability | None
    matched_share: float
    per_category: dict[str, int]
    cpp: Decimal
    cpp_basis: str
    limitations: list[str] = field(default_factory=list)
    top: list[str] = field(default_factory=list)

    @property
    def ongoing(self) -> int:
        return self.rewards_cents + self.credits_cents - self.annual_fee_cents

    @property
    def first_year(self) -> int:
        return self.rewards_cents + self.credits_cents - self.first_year_fee_cents + self.promo_cents


def _profile_min(guidance: str | None) -> int | None:
    if not guidance:
        return None
    found = [r for k, r in PROFILE_RANK.items() if k in guidance.lower()]
    return min(found) if found else None


def _value_cents(units: Decimal, unit: str, cpp: Decimal) -> Decimal:
    """units = spend dollars × rate. pct → cents directly (rate% of dollars ×100/100); x → points × cpp."""
    return units if unit == "pct" else units * cpp


def _months_active(r: RateView, now: datetime) -> Decimal:
    if r.ends_on is None:
        return Decimal(12)
    months = (
        (r.ends_on.year - now.year) * 12
        + (r.ends_on.month - now.month)
        + (1 if r.ends_on.day >= now.day else 0)
    )
    return Decimal(max(0, min(12, months)))


_RESTRICTIVE = {"portal_only", "booked_direct", "partner_only"}
_NOTE_KINDS = {
    "us_only": "U.S. purchases only",
    "excludes_superstores": "superstores are excluded",
    "excludes_warehouse_clubs": "warehouse clubs are excluded",
    "enrollment_required": "enrollment or activation required",
}


def condition_kinds(r: RateView) -> set[str]:
    return {c.kind for c in r.conditions} | ({"portal_only"} if r.portal_only else set())


def rate_applies(r: RateView, req: CardRequest, d: dict[str, object]) -> bool:
    """Whether a rate's qualifiers let it count for this user (DESIGN §24.17 A): portal-only and booked-direct
    rates need the user's opt-in, a partner-only rate needs that partner as the preferred partner. Other qualifiers
    (U.S. only, superstore exclusions, enrollment) count, with a note."""
    kinds = condition_kinds(r)
    if "portal_only" in kinds and not req.opt_in_portal:
        return False
    if "booked_direct" in kinds and not req.opt_in_booked_direct:
        return False
    if "partner_only" in kinds:
        partner = str(
            d.get("co_brand_partner") or next((c.detail for c in r.conditions if c.detail), "") or ""
        )
        if not (req.preferred_partner and partner and req.preferred_partner.lower() in partner.lower()):
            return False
    return True


def annual_rewards(
    p: ProductView, req: CardRequest, cpp: Decimal, now: datetime
) -> tuple[int, dict[str, int], float, list[str]]:
    """Σ min(spend, cap)×rate + overflow×post-cap + remaining×base. Returns (cents, per-category, share, notes)."""
    cfg = scoring()["credit_card"]
    base_unit = "pct" if p.details.get("reward_currency") == "cashback" else "x"
    base = Decimal(str(p.details.get("base_rate") or 0))
    spend = req.monthly_spend.model_dump()
    annual = {k: Decimal(v * 12) for k, v in spend.items()}
    total = sum(annual.values(), Decimal(0))
    notes: list[str] = []
    rates = [r for r in p.reward_rates if r.category not in {"other"}]
    left_out = [r for r in rates if not rate_applies(r, req, p.details)]
    kinds_out = set().union(*(condition_kinds(r) for r in left_out)) if left_out else set()
    if "portal_only" in kinds_out:
        notes.append("Portal-only rates are not included in estimates (valued at the base rate).")
    if "booked_direct" in kinds_out:
        notes.append(
            "Rates for booking directly with the airline or hotel are not included (you didn't opt in)."
        )
    if "partner_only" in kinds_out:
        notes.append("Rates at the co-brand partner are not included unless it is your preferred partner.")
    rates = [r for r in rates if rate_applies(r, req, p.details)]
    remaining = dict(annual)
    value = Decimal(0)
    per_cat: dict[str, int] = {}
    matched = Decimal(0)
    group_cap_left: dict[str, Decimal] = {}

    for user_cat, card_cats in cfg["category_map"].items():
        best: RateView | None = None
        for r in rates:
            if r.category in card_cats and not r.is_rotating and (best is None or r.rate > best.rate):
                best = r
        if best is None or annual[user_cat] == 0:
            continue
        frac = _months_active(best, now) / 12
        if frac < 1:
            notes.append(
                f"{_r(best.rate, best.rate_unit)} on {best.category.replace('_', ' ')} ends "
                f"{best.ends_on}; counted only until then."
            )
        eligible = annual[user_cat] * frac
        cap = None
        if best.cap_cents is not None and best.cap_period:
            cap = Decimal(best.cap_cents) / 100 * PERIODS.get(best.cap_period, 1)
            if best.cap_combined and best.cap_group:
                cap = group_cap_left.setdefault(best.cap_group, cap)
        in_cap = min(eligible, cap) if cap is not None else eligible
        if cap is not None and best.cap_combined and best.cap_group:
            group_cap_left[best.cap_group] = cap - in_cap
        overflow = eligible - in_cap
        post = best.post_cap_rate if best.post_cap_rate is not None else base
        v = _value_cents(in_cap * best.rate, best.rate_unit, cpp) + _value_cents(
            overflow * post, base_unit, cpp
        )
        value += v
        per_cat[user_cat] = int(v)
        remaining[user_cat] = annual[user_cat] - eligible
        if best.rate > base:
            matched += in_cap
        if best.requires_activation:
            notes.append(f"{best.category.replace('_', ' ').capitalize()} rate requires activation.")
        for k in sorted(condition_kinds(best) & set(_NOTE_KINDS) - {"enrollment_required"}):
            notes.append(f"{best.category.replace('_', ' ').capitalize()}: {_NOTE_KINDS[k]}.")
        if cap is not None:
            notes.append(
                f"{best.category.replace('_', ' ').capitalize()}: {_r(best.rate, best.rate_unit)} up to "
                f"{usd(int(Decimal(best.cap_cents or 0)))} per {PERIOD_NOUN.get(best.cap_period or '', best.cap_period or '')}, "
                f"then {_r(post, base_unit)}."
            )

    rotating = [r for r in p.reward_rates if r.is_rotating]
    if rotating:
        r = rotating[0]
        if req.opt_in_rotating and r.cap_cents and r.cap_period:
            rot_share = Decimal(str(cfg["assumptions"]["rotating_spend_share"]))
            cap = Decimal(r.cap_cents) / 100 * PERIODS.get(r.cap_period, 4)
            pool = sum(remaining.values(), Decimal(0))
            eligible = min(cap, pool * rot_share)
            value += _value_cents(eligible * r.rate, r.rate_unit, cpp)
            per_cat["rotating"] = int(_value_cents(eligible * r.rate, r.rate_unit, cpp))
            matched += eligible
            take = eligible
            for k in list(remaining):
                cut = min(remaining[k], take)
                remaining[k] -= cut
                take -= cut
            notes.append(
                f"Rotating categories counted at {_r(r.rate, r.rate_unit)} on "
                f"{usd(int(eligible * 100))} a year (assumes {int(rot_share * 100)}% of your spend falls in "
                "each quarter's categories, up to the published cap; activation required)."
            )
        else:
            notes.append("Rotating bonus categories are counted at the base rate (opt in to include them).")
    rest = sum(remaining.values(), Decimal(0))
    base_v = _value_cents(rest * base, base_unit, cpp)
    value += base_v
    per_cat["everything_else"] = int(base_v)
    share = float(matched / total) if total else 0.0
    return int(value), per_cat, share, notes


def _tiered_bonus(o: OfferView, req: CardRequest, cpp: Decimal) -> tuple[int, Achievability]:
    """Count only the tiers whose (cumulative) spend the user reaches within that tier's window."""
    default_m = scoring()["credit_card"]["assumptions"]["first_months_for_bonus"]
    monthly = Decimal(str(req.monthly_spend.total)) * 100
    total, cum, parts = 0, 0, []
    for t in o.tiers:
        need = t.get("requirement_min_cents")
        if need is None:
            parts.append(f"{t['amount']:,} not counted (no spending requirement to check)")
            continue
        cum = cum + need if t.get("incremental") else need
        wm = period_months(t.get("window_count"), t.get("window_unit"))
        days = t.get("window_days")
        months = (
            Decimal(str(round(wm, 2)))
            if wm is not None
            else Decimal(days) / Decimal(30)
            if days
            else Decimal(str(default_m))
        )
        if monthly * months >= cum:
            total += t["amount"]
            parts.append(f"{t['amount']:,} counted ({usd(cum)} within {months:g} months)")
        else:
            parts.append(f"{t['amount']:,} not counted ({usd(cum)} not reached within {months:g} months)")
    value = total if o.reward_unit == "cents" else int(Decimal(total) * cpp)
    return value, Achievability(achievable=total > 0, explanation="Tiered offer: " + "; ".join(parts) + ".")


def _bonus(o: OfferView, req: CardRequest, cpp: Decimal) -> tuple[int, Achievability]:
    if o.amount_qualifier == "tiered" and o.tiers:
        return _tiered_bonus(o, req, cpp)
    req_cents = worst_case_requirement(o)
    months = window_months(o, scoring()["credit_card"]["assumptions"]["first_months_for_bonus"])
    projected = int(req.monthly_spend.total * months * 100)
    if o.requirement_type != "spend" or req_cents is None:
        return 0, Achievability(
            achievable=False,
            explanation="The spending requirement could not be confirmed, so the bonus is not counted.",
        )
    ok = projected >= req_cents
    expl = (
        f"{'Yes' if ok else 'No'}: your estimated {usd(req.monthly_spend.total * 100)}/month × "
        f"{months:g} months = {usd(projected)} {'meets' if ok else 'is below'} the {usd(req_cents)} requirement."
    )
    if not ok or o.amount_qualifier != "exact" or o.amount_max is None:
        return 0, Achievability(achievable=ok, explanation=expl)
    value = o.amount_max if o.reward_unit == "cents" else int(Decimal(o.amount_max) * cpp)
    return value, Achievability(achievable=True, explanation=expl)


def _fee_for_year(p: ProductView, year: int, now: datetime) -> int:
    """Annual fee charged at the start of account year ``year`` (1-based), using intro waivers and any scheduled
    fee change whose effective date falls on or before that year's start."""
    d = p.details
    if (
        year == 1
        and d.get("intro_annual_fee_cents") is not None
        and (d.get("intro_annual_fee_months") or 0) >= 12
    ):
        return int(d["intro_annual_fee_cents"])
    eff, fut = d.get("annual_fee_effective_date"), d.get("future_annual_fee_cents")
    start = now.date().replace(year=now.year + year - 1)
    if eff is not None and fut is not None and eff <= start:
        return int(fut)
    return int(d.get("annual_fee_cents") or 0)


def calc(p: ProductView, req: CardRequest, now: datetime) -> CardCalc:
    cpp, basis = cents_per_point(p.details.get("reward_program"), req.cents_per_point)
    rewards, per_cat, share, notes = annual_rewards(p, req, cpp, now)
    credits = []
    credit_total = 0
    for b in p.benefits:
        if b.monetizable and b.id in req.selected_credit_ids and b.annual_value_cents:
            credits.append({"id": b.id, "name": b.name, "annual_value_cents": b.annual_value_cents})
            credit_total += b.annual_value_cents
    offers = eligible_offers(p)
    exact = next((o for o in offers if o.amount_qualifier in {"exact", "tiered"}), None)
    possible = next((o for o in offers if o.amount_qualifier in {"up_to", "starting_at"}), None)
    promo, ach = (0, None)
    if exact is not None:
        promo, ach = _bonus(exact, req, cpp)
    elif possible is not None:
        _, ach = _bonus(possible, req, cpp)
    c = CardCalc(
        p,
        rewards,
        credit_total,
        credits,
        int(p.details.get("annual_fee_cents") or 0),
        _fee_for_year(p, 1, now),
        _fee_for_year(p, 2, now),
        _fee_for_year(p, 3, now),
        promo,
        exact,
        possible,
        ach,
        share,
        per_cat,
        cpp,
        basis,
        notes,
    )
    c.top = [
        k for k, v in sorted(per_cat.items(), key=lambda kv: -kv[1]) if v > 0 and k != "everything_else"
    ][:3]
    return c


def _filters(p: ProductView, req: CardRequest) -> str | None:
    d = p.details
    if p.label != "verified":
        return "not Verified"
    if req.segment != "either" and d.get("segment") != req.segment:
        return f"{d.get('segment')} card"
    fee = int(d.get("annual_fee_cents") or 0)
    if req.exclude_over_max_fee and fee > req.max_annual_fee * 100:
        return f"annual fee {usd(fee)} is above your maximum"
    if req.card_kind == "secured" and not d.get("is_secured"):
        return "not a secured card"
    if req.card_kind == "student" and not d.get("is_student"):
        return "not a student card"
    if req.card_kind == "any" and req.goal != "build_credit" and (d.get("is_secured") or d.get("is_student")):
        return "secured/student card (choose that option to include)"
    if not req.include_co_branded and d.get("is_co_branded"):
        return "co-branded card"
    pmin = _profile_min(d.get("credit_profile_guidance"))
    if pmin is not None and req.credit_profile != "unknown" and PROFILE_RANK[req.credit_profile] < pmin:
        return "issuer's published credit guidance is above your range"
    if (
        req.goal == "low_interest"
        and d.get("purchase_apr_min_pct") is None
        and d.get("intro_purchase_apr_months") is None
    ):
        return "no verified APR (needed for a low-interest goal)"
    if d.get("rewards_program") == "none" and req.goal not in NO_REWARDS_GOALS:
        return (
            "no rewards program (eligible only for low-interest, balance-transfer and credit-building goals)"
        )
    if req.avoid_foreign_fee and d.get("foreign_tx_fee_pct") is None:
        return "no verified foreign transaction fee (you asked to avoid foreign transaction fees)"
    if req.goal == "balance_transfer" and d.get("intro_bt_apr_months") is None:
        return "no verified balance-transfer intro APR"
    if req.preferred_reward != "any" and d.get("reward_currency") not in {req.preferred_reward, None}:
        return f"earns {d.get('reward_currency')}, you prefer {req.preferred_reward}"
    return None


def _goal(c: CardCalc, req: CardRequest) -> float:
    d = c.p.details
    base = Decimal(str(d.get("base_rate") or 0))
    if req.goal == "cashback":
        return 1.0 if d.get("reward_currency") == "cashback" else 0.3
    if req.goal == "travel":
        travel_rate = any(
            r.category in TRAVEL_BENEFITS and r.rate > base and rate_applies(r, req, d)
            for r in c.p.reward_rates
        )
        no_ftf = d.get("foreign_tx_fee_pct") is not None and Decimal(str(d["foreign_tx_fee_pct"])) == 0
        perks = any(b.benefit_type in TRAVEL_BENEFITS for b in c.p.benefits)
        partner = bool(
            req.preferred_partner
            and d.get("co_brand_partner")
            and req.preferred_partner.lower() in str(d["co_brand_partner"]).lower()
        )
        return clip(0.4 * travel_rate + 0.25 * no_ftf + 0.25 * perks + 0.1 * partner)
    if req.goal == "welcome_bonus":
        return 1.0 if c.promo_cents > 0 else 0.3 if c.possible else 0.0
    if req.goal == "low_interest":
        months = d.get("intro_purchase_apr_months") or 0
        apr = d.get("purchase_apr_min_pct")
        low = 1 - (float(apr) - 15) / 20 if apr is not None else 0.0
        return clip(0.6 * min(months, 21) / 21 + 0.4 * clip(low))
    if req.goal == "balance_transfer":
        months = d.get("intro_bt_apr_months") or 0
        fee = float(d.get("bt_fee_pct") or 5)
        return clip(min(months, 21) / 21 * (1 - fee / 10))
    # build_credit
    if d.get("is_secured") or d.get("is_student"):
        return 1.0
    return 0.6 if int(d.get("annual_fee_cents") or 0) == 0 else 0.2


def _break_even(c: CardCalc) -> str | None:
    if c.annual_fee_cents <= 0:
        return "No annual fee."
    best = max(
        (r for r in c.p.reward_rates if not condition_kinds(r) & _RESTRICTIVE and not r.is_rotating),
        key=lambda r: r.rate,
        default=None,
    )
    if best is None or best.rate <= 0:
        return None
    per_dollar = _value_cents(best.rate, best.rate_unit, c.cpp)  # cents per $1 spent
    monthly = Decimal(c.annual_fee_cents) / per_dollar / 12
    cat = "all purchases" if best.category == "other" else best.category.replace("_", " ")
    return f"This card's fee is covered if you spend at least {usd(int(monthly * 100))}/month in {cat}."


def recommend(
    products: list[ProductView], req: CardRequest, now: datetime | None = None
) -> RecommendResponse:
    now = now or datetime.now(UTC)
    cfg = scoring()
    weights = dict(cfg["credit_card"]["weights"])
    weights["first_year"] *= cfg["bonus_importance_multiplier"][req.bonus_importance]
    sig = cfg["credit_card"]["possible_offer_signal"]
    use_signal = list(cfg["bonus_importance_multiplier"]).index(req.bonus_importance) >= list(
        cfg["bonus_importance_multiplier"]
    ).index(sig["min_bonus_importance"])
    if use_signal:
        weights["possible_offer_signal"] = sig["weight"]
    excluded: list[Excluded] = []
    calcs: list[CardCalc] = []
    for p in products:
        if p.product_type != "credit_card":
            continue
        why_not = _filters(p, req)
        if why_not:
            excluded.append(Excluded(product_id=p.id, name=p.name, reason=why_not))
            continue
        c = calc(p, req, now)
        if c.annual_fee_cents > req.max_annual_fee * 100 and c.ongoing <= 0:
            excluded.append(
                Excluded(
                    product_id=p.id,
                    name=p.name,
                    reason="annual fee above your maximum and not covered by estimated value",
                )
            )
            continue
        calcs.append(c)
    ongoing_n = minmax([c.ongoing for c in calcs])
    first_n = minmax([c.first_year for c in calcs])
    results: list[Result] = []
    for i, c in enumerate(calcs):
        d = c.p.details
        ftf = d.get("foreign_tx_fee_pct")
        travel_n = (
            1.0
            if req.travel_frequency == "none"
            else (
                {"occasional": 0.5, "frequent": 1.0}[req.travel_frequency]
                * any(b.benefit_type in TRAVEL_BENEFITS for b in c.p.benefits)
            )
        )
        pmin = _profile_min(d.get("credit_profile_guidance"))
        prof = (
            1.0
            if pmin is None or req.credit_profile == "unknown"
            else (1.0 if PROFILE_RANK[req.credit_profile] >= pmin else 0.5)
        )
        raw = {
            "ongoing": ongoing_n[i],
            "first_year": first_n[i],
            "category_match": c.matched_share,
            "goal_match": _goal(c, req),
            "foreign_fee_fit": 1.0
            if not req.avoid_foreign_fee
            else (1.0 if ftf is not None and Decimal(str(ftf)) == 0 else 0.0),
            "travel_benefit_fit": travel_n,
            "credit_profile_fit": prof,
            "completeness": completeness(c.p),
        }
        if use_signal:
            sig_n = 0.0
            if c.possible is not None and c.offer is None:
                sig_n = 0.5 if c.achievability is None else (1.0 if c.achievability.achievable else 0.0)
            raw["possible_offer_signal"] = sig_n
        score, comps = components(raw, weights)
        results.append(_result(c, req, score, comps, now))
    results.sort(key=lambda r: (-r.score, -r.values.ongoing_annual_cents, r.product.name))
    for n, r in enumerate(results, start=1):
        r.rank = n
    return RecommendResponse(
        product_type="credit_card",
        generated_at=now,
        results=results,
        excluded=excluded,
        disclaimer=DISCLAIMER,
    )


def _result(c: CardCalc, req: CardRequest, score: float, comps: list[Any], now: datetime) -> Result:
    d = c.p.details
    y1 = c.first_year
    y2 = c.rewards_cents + c.credits_cents - c.fee_y2_cents
    y3 = c.rewards_cents + c.credits_cents - c.fee_y3_cents
    nonmon = [b.name for b in c.p.benefits if not b.monetizable or b.id not in req.selected_credit_ids]
    values = Values(
        ongoing_annual_cents=c.ongoing,
        promotional_cents=c.promo_cents,
        first_year_cents=c.first_year,
        year1_cents=y1,
        year2_cents=y2,
        year3_cents=y3,
        three_year_total_cents=y1 + y2 + y3,
        non_monetized=nonmon,
        credits_counted=c.credits_counted,
    )
    fee = c.annual_fee_cents
    fee_text = f"{usd(fee)} annual fee" if fee else "No annual fee"
    if c.first_year_fee_cents != fee:
        fee_text += f" ({usd(c.first_year_fee_cents)} the first year)"
    if c.fee_y2_cents != fee:
        fee_text += f"; scheduled to change to {usd(c.fee_y2_cents)}"
    possible = None
    if c.possible is not None and c.offer is None:
        unit = {"cents": "", "points": " points", "miles": " miles"}[c.possible.reward_unit]
        amt = c.possible.amount_max if c.possible.amount_qualifier == "up_to" else c.possible.amount_min
        word = "up to" if c.possible.amount_qualifier == "up_to" else "at least"
        shown = usd(amt or 0) if c.possible.reward_unit == "cents" else f"{amt:,}{unit}"
        possible = (
            f"Possible welcome offer: {word} {shown} (your offer is shown during application and may be "
            "lower)."
            if word == "up to"
            else f"Possible welcome offer: {word} {shown} (not counted in "
            "dollar values because the final amount is not stated)."
        )
    why: list[Reason] = []
    top = sorted(comps, key=lambda x: -x.contribution)
    for comp in top[:3]:
        why.append(_reason(comp.key, c, req))
    lim = list(c.limitations)
    if d.get("purchase_apr_min_pct") is None:
        lim.append("APR: see issuer.")
    if c.p.reward_rates and d.get("reward_currency") != "cashback":
        pass
    assumptions = []
    if d.get("reward_currency") in {"points", "miles"}:
        assumptions.append(f"Assumes {c.cpp.normalize():f}¢ per point ({c.cpp_basis}).")
    assumptions.append("Spending is spread evenly across the year; rewards use your stated monthly amounts.")
    over = None
    if fee > req.max_annual_fee * 100:
        over = f"Annual fee is above your maximum; estimated value exceeds the fee by {usd(c.ongoing)} under your inputs."
    note = None
    if c.offer is not None and c.offer.note:
        note = c.offer.note
    elif c.p.offer_absent_note and c.offer is None and c.possible is None:
        note = c.p.offer_absent_note
    return Result(
        rank=0,
        product=c.p,
        score=score,
        components=comps,
        values=values,
        fee_text=fee_text,
        current_offer=c.offer or c.possible,
        possible_welcome_offer=possible,
        offer_note=note,
        achievability=c.achievability,
        break_even=_break_even(c),
        over_budget_note=over,
        top_features=[t.replace("_", " ") for t in c.top],
        why=why,
        limitations=lim,
        assumptions=assumptions,
    )


def _reason(key: str, c: CardCalc, req: CardRequest) -> Reason:
    d = c.p.details
    if key == "category_match":
        cats = [t.replace("_", " ") for t in c.top]
        return Reason(
            code=key,
            params={"categories": cats, "share": round(c.matched_share, 2)},
            text=f"{int(c.matched_share * 100)}% of your spending earns a bonus rate"
            + (f" ({', '.join(cats)})." if cats else "."),
        )
    if key == "ongoing":
        return Reason(
            code=key,
            params={"cents": c.ongoing},
            text=f"Estimated ongoing value of {usd(c.ongoing)} a year after fees.",
        )
    if key == "first_year":
        return Reason(
            code=key,
            params={"cents": c.first_year},
            text=f"Estimated first-year value of {usd(c.first_year)}"
            + (f", including a {usd(c.promo_cents)} welcome bonus you can reach." if c.promo_cents else "."),
        )
    if key == "goal_match":
        return Reason(
            code=key, params={"goal": req.goal}, text=f"Matches your goal: {req.goal.replace('_', ' ')}."
        )
    if key == "foreign_fee_fit":
        return Reason(
            code=key,
            text="No foreign transaction fee."
            if d.get("foreign_tx_fee_pct") is not None and Decimal(str(d["foreign_tx_fee_pct"])) == 0
            else "Foreign transaction fee applies."
            if d.get("foreign_tx_fee_pct") is not None
            else "Foreign transaction fee not verified — check the issuer.",
        )
    if key == "possible_offer_signal":
        return Reason(
            code=key,
            text="Small ranking boost: advertises a possible welcome offer (not included in "
            "dollar estimates).",
        )
    if key == "completeness":
        return Reason(code=key, text="Key terms are verified on the issuer's site.")
    if key == "credit_profile_fit":
        return Reason(code=key, text="Fits the issuer's published credit guidance (or none is published).")
    return Reason(code=key, text="Travel benefits fit how often you travel.")
