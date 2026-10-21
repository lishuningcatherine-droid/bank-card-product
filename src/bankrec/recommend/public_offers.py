"""Public offer ranking for the home page (DESIGN §25.3): no user inputs, no scores — dollar estimates only.

Each Verified product contributes its best *public, current* offer. The estimate is the bonus in dollars: cash as
stated, points and miles at the cents-per-point in config/point_values.yaml (published on the methodology page). For
a card the first-year annual fee is subtracted; for a deposit account the monthly fee is shown but not subtracted,
because whether it is charged depends on waivers the visitor may meet. "Up to" and "starting at" amounts are never
valued: they are listed apart, unranked. Targeted, referral and pre-approved offers are never ranked.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field

from bankrec.recommend.common import DISCLAIMER, eligible_offers
from bankrec.recommend.config import cents_per_point, point_values
from bankrec.recommend.models import OfferView, ProductView

Sort = Literal["value", "bonus", "requirement", "ending"]
# cash: cash bonuses and points with an issuer-published fixed cash value; points: every other point or mile, whose
# dollar figure is only an estimate at the default value (owner decision 2026-10-20: never ranked together)
Group = Literal["cash", "points"]


class OfferEstimate(BaseModel):
    group: Group = "cash"
    bonus_value_cents: int
    # "cash", "fixed value: 1.0¢ per point (basis)" or "estimated, assumes 1.0¢/point"
    value_basis: str
    cents_per_point: Decimal | None = None
    first_year_fee_cents: int | None = None  # cards: annual fee charged in the first year, when stated
    monthly_fee_cents: int | None = None  # deposit accounts: shown, not subtracted
    net_first_year_cents: int | None = (
        None  # cards: bonus minus first-year fee; None when the fee is not stated
    )


class ProductBrief(BaseModel):
    id: str
    name: str
    bank_name: str
    product_type: str
    official_url: str
    label: str


class RankedOffer(BaseModel):
    rank: int
    product: ProductBrief
    offer: OfferView
    estimate: OfferEstimate
    # the same product's other public offers on other official pages (channels), and how many non-public ones exist
    other_public_offers: list[OfferView] = Field(default_factory=list)
    non_public_offers: int = 0


class UnrankedOffer(BaseModel):
    product: ProductBrief
    offer: OfferView
    reason: str


class PublicOffersResponse(BaseModel):
    product_type: str
    group: Group = "cash"
    sort: Sort
    generated_at: datetime
    items: list[RankedOffer]
    unranked: list[UnrankedOffer]
    assumptions: list[str]
    point_values: dict[str, object]
    disclaimer: str = DISCLAIMER


def _brief(p: ProductView) -> ProductBrief:
    return ProductBrief(
        id=p.id,
        name=p.name,
        bank_name=p.bank_name,
        product_type=p.product_type,
        official_url=p.official_url,
        label=p.label,
    )


def _cents(v: Decimal) -> int:
    return int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _cpp_text(cpp: Decimal) -> str:
    s = f"{cpp.normalize():f}"
    return s if "." in s else f"{s}.0"


def fixed_value(program: object) -> bool:
    """True only for a program listed with an issuer-published fixed cash-redemption value."""
    prog = (point_values().get("programs") or {}).get(str(program or ""))
    return bool(prog and prog.get("fixed_cash_value"))


def estimate(p: ProductView, o: OfferView) -> OfferEstimate | str:
    """The dollar estimate of ``o``, or the reason it is not valued."""
    if o.amount_qualifier not in ("exact", "tiered") or o.amount_max is None:
        return "the bank states an “up to” or “starting at” amount, so it is not valued"
    d = p.details
    if o.reward_unit == "cents":
        value, basis, cpp = o.amount_max, "cash", None
    elif d.get("reward_currency") == "restricted":
        return "the bonus is paid in a store currency with limited redemption, so it is not valued as cash"
    else:
        cpp, src = cents_per_point(d.get("reward_program"))
        unit = "mile" if o.reward_unit == "miles" else "point"
        value = _cents(Decimal(o.amount_max) * cpp)
        if fixed_value(d.get("reward_program")):
            basis = f"fixed value: {_cpp_text(cpp)}¢ per {unit} ({src})"
        else:
            basis = f"estimated, assumes {_cpp_text(cpp)}¢/{unit}"
    group: Group = "cash" if o.reward_unit == "cents" or fixed_value(d.get("reward_program")) else "points"
    est = OfferEstimate(group=group, bonus_value_cents=value, value_basis=basis, cents_per_point=cpp)
    if p.product_type == "credit_card":
        fee = d.get("intro_annual_fee_cents")
        fee = d.get("annual_fee_cents") if fee is None else fee
        est.first_year_fee_cents = None if fee is None else int(fee)
        est.net_first_year_cents = None if fee is None else value - int(fee)
    else:
        mf = d.get("monthly_fee_cents")
        est.monthly_fee_cents = None if mf is None else int(mf)
    return est


def _key(sort: Sort, r: RankedOffer) -> tuple[object, ...]:
    e, o = r.estimate, r.offer
    far = date.max
    if sort == "bonus":
        return (-e.bonus_value_cents, r.product.name)
    if sort == "requirement":
        req = o.requirement_min_cents if o.requirement_min_cents is not None else o.requirement_max_cents
        return (req is None, req or 0, -e.bonus_value_cents, r.product.name)
    if sort == "ending":
        return (o.expiration_date or far, -e.bonus_value_cents, r.product.name)
    # value: cards by bonus minus first-year fee (unknown fee last), deposits by bonus
    net = e.net_first_year_cents if r.product.product_type == "credit_card" else e.bonus_value_cents
    return (net is None, -(net or 0), r.product.name)


def ranking_assumptions() -> list[str]:
    """The rules behind the public offer ranking, served with it and on the methodology page."""
    pv = point_values()
    return [
        "Only Verified products and current, public offers from official bank pages are ranked.",
        "Cash offers (cash back, and points with an issuer-published fixed cash value) and points or miles offers "
        "are ranked separately, never together.",
        f"Points and miles without a fixed cash value are shown in their own amounts; their dollar figure is an "
        f"estimate that assumes {pv['default_cents_per_point']}¢ each, and portal or transfer-partner values are "
        "not used.",
        "Card estimates subtract the annual fee charged in the first year; a card whose fee is not stated is "
        "listed after the others.",
        "Deposit-account estimates are the bonus itself; the monthly fee is shown but not subtracted, because "
        "it depends on the waivers you meet.",
        "Each estimate assumes you meet the stated requirement in time; money spent or deposited to qualify is "
        "not counted as value.",
        "“Up to” and “starting at” offers, and targeted, referral or pre-approved offers, are never ranked.",
    ]


def rank(
    products: list[ProductView],
    product_type: str,
    sort: Sort,
    now: datetime,
    limit: int = 50,
    group: Group = "cash",
) -> PublicOffersResponse:
    items: list[RankedOffer] = []
    unranked: list[UnrankedOffer] = []
    for p in products:
        if p.product_type != product_type or p.label != "verified":
            continue
        public = eligible_offers(p)
        if not public:
            continue
        non_public = sum(1 for o in p.offers if o.audience != "public" and o.state == "current")
        all_valued = [(o, e) for o in public if isinstance(e := estimate(p, o), OfferEstimate)]
        valued = [(o, e) for o, e in all_valued if e.group == group]
        if not all_valued:
            o = public[0]
            reason = estimate(p, o)
            assert isinstance(reason, str)
            unranked.append(UnrankedOffer(product=_brief(p), offer=o, reason=reason))
            continue
        if not valued:
            continue
        best, est = max(
            valued, key=lambda oe: (oe[1].bonus_value_cents, -(oe[0].expiration_date or date.max).toordinal())
        )
        items.append(
            RankedOffer(
                rank=0,
                product=_brief(p),
                offer=best,
                estimate=est,
                other_public_offers=[o for o in public if o.id != best.id],
                non_public_offers=non_public,
            )
        )
    items.sort(key=lambda r: _key(sort, r))
    items = items[:limit]
    for n, r in enumerate(items, start=1):
        r.rank = n
    pv = point_values()
    assumptions = ranking_assumptions()
    return PublicOffersResponse(
        product_type=product_type,
        group=group,
        sort=sort,
        generated_at=now,
        items=items,
        unranked=sorted(unranked, key=lambda u: u.product.name),
        assumptions=assumptions,
        point_values=pv,
    )
