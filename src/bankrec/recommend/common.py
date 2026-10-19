"""Shared scoring helpers."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from bankrec.recommend.models import Component, OfferView, ProductView

DISCLAIMER = (
    "Not financial advice. Product terms change; confirm all details on the official bank website before applying. "
    "Data is checked on a schedule and is not real-time. We have no affiliate or advertiser relationships, and "
    "rankings are not paid."
)

LABELS = {
    "ongoing": "Ongoing annual value",
    "first_year": "First-year value",
    "category_match": "Fit with your spending",
    "goal_match": "Fit with your goal",
    "foreign_fee_fit": "Foreign transaction fee",
    "travel_benefit_fit": "Travel benefits",
    "credit_profile_fit": "Issuer credit guidance",
    "completeness": "Data completeness",
    "possible_offer_signal": "Possible welcome offer (not in dollar values)",
    "net_value": "Net value",
    "achievability_margin": "Bonus requirement margin",
    "qualification_time": "Time to qualify",
    "holding_requirement": "Holding requirement",
    "balance_burden": "Minimum balance burden",
    "branch_fit": "Branch / online fit",
    "apy": "APY",
    "bonus": "Bonus",
    "liquidity_fit": "Access to your money",
    "fee_fit": "Fees",
}


def usd(cents: int | Decimal) -> str:
    c = int(cents)
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}${c // 100:,}" + (f".{c % 100:02d}" if c % 100 else "")


def minmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 if hi > 0 else 0.0 for _ in values]
    return [max(0.0, (v - lo) / (hi - lo)) for v in values]


def clip(v: float) -> float:
    return max(0.0, min(1.0, v))


def components(raw: dict[str, float], weights: dict[str, float]) -> tuple[float, list[Component]]:
    total_w = sum(weights[k] for k in raw if k in weights) or 1.0
    comps = []
    score = 0.0
    for k, n in raw.items():
        w = weights.get(k, 0.0)
        contribution = 100.0 * w * clip(n) / total_w
        score += contribution
        comps.append(
            Component(
                key=k,
                label=LABELS.get(k, k),
                weight=round(w, 4),
                normalized=round(clip(n), 4),
                contribution=round(contribution, 2),
            )
        )
    comps.sort(key=lambda c: -c.contribution)
    return round(score, 2), comps


def eligible_offers(p: ProductView) -> list[OfferView]:
    """Current, public, fresh, not expired, not recheck-pending — evaluated at request time by the repository."""
    return [o for o in p.offers if o.state == "current"]


# Scoring-time approximations only (stored values keep the page's unit): a month is 30 days, a billing cycle or
# statement closing about one month.
_MONTHS_PER = {"days": 1 / 30, "weeks": 7 / 30, "months": 1.0, "years": 12.0, "billing_cycles": 1.0}


def period_months(count: int | None, unit: str | None) -> float | None:
    if not count or unit not in _MONTHS_PER:
        return None
    return count * _MONTHS_PER[unit]


def window_months(o: OfferView, default: int = 3) -> float:
    m = period_months(o.qualification_window_count, o.qualification_window_unit)
    if m is not None:
        return m
    if o.qualification_window_months:
        return float(o.qualification_window_months)
    if o.qualification_window_days:
        return o.qualification_window_days / 30.0
    return float(default)


def holding_days(o: OfferView) -> int:
    m = period_months(o.holding_period_count, o.holding_period_unit)
    if m is not None:
        return round(m * 30)
    return o.holding_period_days or 0


def worst_case_requirement(o: OfferView) -> int | None:
    """Requirement used for achievability: the stated max when it varies, else the exact amount."""
    if o.requirement_qualifier == "up_to":
        return o.requirement_max_cents
    return o.requirement_min_cents if o.requirement_min_cents is not None else o.requirement_max_cents


def completeness(p: ProductView) -> float:
    total = len(p.details) or 1
    return clip(1 - len(p.missing_fields) / total)


def deposit_notes(p: ProductView, offer: OfferView | None) -> list[str]:
    """Bank-stated terms the recommender cannot check from the user's inputs, quoted for the result: who may open the
    account, who may receive its bonus, and a new-account fee waiver (DESIGN §24.22)."""
    d = p.details
    out = []
    if who := d.get("customer_eligibility") or d.get("customer_restrictions"):
        out.append(f"Who can open (as stated by the bank): {who}")
    if offer is not None and offer.eligibility_restrictions:
        out.append(f"Bonus eligibility (as stated by the bank): {offer.eligibility_restrictions}")
    iw = d.get("intro_fee_waiver")
    if isinstance(iw, dict) and iw.get("count"):
        unit = "statement periods" if iw.get("unit") == "statement_period" else "months"
        least = "at least " if iw.get("qualifier") == "at_least" else ""
        out.append(f"New accounts: monthly fee waived for {least}the first {iw['count']} {unit}.")
    return out


def intro_waived_months(p: ProductView) -> int:
    """Months of fee the new-account waiver removes from a first-year estimate. Only a waiver stated in months counts;
    statement periods are never converted to months, so they do not lower the estimate."""
    iw = p.details.get("intro_fee_waiver")
    if isinstance(iw, dict) and iw.get("unit") == "month" and isinstance(iw.get("count"), int):
        return min(12, int(iw["count"]))
    return 0
