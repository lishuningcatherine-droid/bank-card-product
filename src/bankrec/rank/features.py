"""Features of one shown result. Product-side and position only: the visitor's answers are never stored (§26.7), so a
learned model can only learn how people respond to products as the baseline ordered them for their answers."""

from __future__ import annotations

import math

from bankrec.recommend.common import eligible_offers
from bankrec.recommend.models import ProductView
from bankrec.recommend.public_offers import OfferEstimate, estimate

FEATURES = ["bias", "inv_position", "has_public_offer", "log_bonus_dollars", "fee_dollars_100"]


def features(p: ProductView, position: int) -> dict[str, float]:
    offers = eligible_offers(p)
    bonus = 0
    for o in offers:
        e = estimate(p, o)
        if isinstance(e, OfferEstimate):
            bonus = max(bonus, e.bonus_value_cents)
    d = p.details
    fee = d.get("annual_fee_cents") if p.product_type == "credit_card" else d.get("monthly_fee_cents")
    if p.product_type != "credit_card" and fee is not None:
        fee = int(fee) * 12
    return {
        "bias": 1.0,
        "inv_position": 1.0 / max(1, position),
        "has_public_offer": 1.0 if offers else 0.0,
        "log_bonus_dollars": math.log1p(bonus / 100),
        "fee_dollars_100": (int(fee) / 100 / 100) if fee is not None else 0.0,
    }
