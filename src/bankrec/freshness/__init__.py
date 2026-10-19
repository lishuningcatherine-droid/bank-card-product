"""Staleness and request-time expiry (DESIGN §11). One function used by API, recommender and reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from bankrec.settings import CONFIG_DIR


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "freshness.yaml").read_text(encoding="utf-8")))


def stale_after(tier: str) -> timedelta:
    return timedelta(days=int(config()["tiers"][tier]["stale_after_days"]))


def is_stale(confirmed_at: datetime | None, tier: str, now: datetime) -> bool:
    return confirmed_at is None or now - confirmed_at > stale_after(tier)


def today_et(now: datetime) -> date:
    return now.astimezone(ZoneInfo(config()["offer_expiry_timezone"])).date()


def offer_state(
    status: str,
    expiration_date: date | None,
    last_confirmed_at: datetime | None,
    now: datetime,
) -> str:
    """current | expired | stale | uncertain | recheck_pending — evaluated at request time. Who the offer is for is
    its ``audience`` (public | targeted | referral | preapproved), kept apart from this lifecycle state."""
    if expiration_date is not None and expiration_date < today_et(now):
        return "expired"
    if status != "current":
        return status
    if is_stale(last_confirmed_at, "offer", now):
        return "stale"
    return "current"


def product_label(
    *,
    published: bool,
    terms_confirmed_at: datetime | None,
    apy_confirmed_at: datetime | None,
    product_type: str,
    missing_key: list[str],
    recheck_pending: bool,
    provider_only_fields: list[str],
    now: datetime,
) -> tuple[str, list[str]]:
    """User-facing label: "verified" | "partially_verified" (+ reasons). Under-review records are never served."""
    reasons: list[str] = []
    if not published:
        return "under_review", ["not published"]
    if is_stale(terms_confirmed_at, "terms", now):
        reasons.append("product terms not recently verified")
    if product_type == "savings" and is_stale(apy_confirmed_at, "apy", now):
        reasons.append("APY not recently verified")
    if missing_key:
        reasons.append("information missing: " + ", ".join(missing_key))
    if recheck_pending:
        reasons.append("recheck pending")
    if provider_only_fields:
        reasons.append("some details come only from licensed data")
    return ("partially_verified" if reasons else "verified"), reasons
