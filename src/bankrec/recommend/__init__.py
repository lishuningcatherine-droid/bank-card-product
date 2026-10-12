"""Deterministic, transparent recommendation engines (no ML)."""

from __future__ import annotations

from datetime import datetime

from bankrec.recommend import cards, checking, savings
from bankrec.recommend.models import (
    CardRequest,
    CheckingRequest,
    ProductView,
    RecommendResponse,
    SavingsRequest,
)


def recommend(
    products: list[ProductView],
    req: CardRequest | CheckingRequest | SavingsRequest,
    now: datetime | None = None,
) -> RecommendResponse:
    if isinstance(req, CardRequest):
        return cards.recommend(products, req, now)
    if isinstance(req, CheckingRequest):
        return checking.recommend(products, req, now)
    return savings.recommend(products, req, now)
