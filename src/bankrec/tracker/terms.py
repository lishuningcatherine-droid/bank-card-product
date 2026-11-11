"""Campaign terms, identity and material changes (DESIGN §27.2).

Identity (dedup key) = card + channel + offer type + reward structure. Material terms are hashed; only a change in
them creates a new version. Everything else on a page (layout, "last updated" stamps, unrelated text) only refreshes
the last-verified time.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from bankrec.db import prod as P
from bankrec.tracker import deadline

CHANNEL = {"public": "public", "targeted": "targeted", "preapproved": "targeted", "referral": "referral"}
OFFER_TYPE = {"card_welcome": "welcome_bonus"}
OFFER_TYPES = ("welcome_bonus", "spend_multiplier", "first_year_fee", "first_year_match", "other")
UNITS = ("cash", "statement_credit", "points", "miles", "free_night", "other")

# the terms that make a new version when they change (brief §3)
MATERIAL = (
    "offer_type",
    "channel",
    "tiers",
    "amount_qualifier",
    "total_amount",
    "unit",
    "min_spend_cents",
    "window_count",
    "window_unit",
    "window_start",
    "annual_fee_cents",
    "first_year_fee_cents",
    "start",
    "end",
    "eligibility_text",
    "guaranteed_min",
    "offer_components",
)
TIER_TERMS = ("amount", "unit", "spend_cents", "window_count", "window_unit", "window_start", "incremental")
# The campaign's channel (public / targeted / referral / branch) is part of its identity. Which official pages showed
# it (``channels_seen``) is recorded but is not a term of the offer, so it never makes a new version.
_WINDOW_START = (
    (
        re.compile(
            r"(?:from|of|after) (?:the date )?(?:your )?account (?:opening|is opened)|from the date your account is opened|account opening",
            re.I,
        ),
        "account_opening",
    ),
    (re.compile(r"of Card Membership", re.I), "card_membership"),
    (re.compile(r"(?:account|card) is approved|upon approval|from approval", re.I), "approval"),
)


def norm(s: str | None) -> str | None:
    return re.sub(r"\s+", " ", s).strip() if s else None


def unit_of(o: P.Offer) -> str:
    if o.reward_unit in ("points", "miles"):
        return o.reward_unit
    if re.search(r"\bstatement credit\b", o.verbatim_text or "", re.I):
        return "statement_credit"
    return "cash"


def window_start(*texts: str | None) -> str:
    joined = " ".join(t for t in texts if t)
    for pat, name in _WINDOW_START:
        if pat.search(joined):
            return name
    return "not_stated"


def from_offer(o: P.Offer, product: P.Product) -> dict[str, Any]:
    """Terms of a published offer, with the card's fees as they stood when it was read."""
    card = product.card
    unit = unit_of(o)
    start = window_start(o.qualification_window_text, o.verbatim_text)
    tiers: list[dict[str, Any]] = []
    if o.tiers:
        for t in o.tiers:
            tiers.append(
                {
                    "amount": t.get("amount"),
                    "unit": unit,
                    "spend_cents": t.get("requirement_min_cents")
                    if t.get("requirement_min_cents") is not None
                    else t.get("requirement_max_cents"),
                    "incremental": bool(t.get("incremental")),
                    "window_count": t.get("window_count") or o.qualification_window_count,
                    "window_unit": t.get("window_unit") or o.qualification_window_unit,
                    "window_start": start,
                    "text": norm(t.get("text")),
                }
            )
    else:
        tiers.append(
            {
                "amount": o.amount_max if o.amount_max is not None else o.amount_min,
                "unit": unit,
                "spend_cents": o.requirement_min_cents
                if o.requirement_min_cents is not None
                else o.requirement_max_cents,
                "window_count": o.qualification_window_count,
                "window_unit": o.qualification_window_unit,
                "window_start": start,
                "text": norm(o.verbatim_text),
            }
        )
    first_year = None
    if card is not None:
        first_year = (
            card.intro_annual_fee_cents if card.intro_annual_fee_cents is not None else card.annual_fee_cents
        )
    return {
        "offer_type": OFFER_TYPE.get(o.offer_type, "other"),
        "channel": CHANNEL.get(o.audience, "public"),
        "tiers": tiers,
        "amount_qualifier": o.amount_qualifier,
        "total_amount": o.amount_max if o.amount_max is not None else o.amount_min,
        "unit": unit,
        "stated_cash_value_cents": o.stated_cash_value_cents,
        "requirement_type": o.requirement_type,
        "min_spend_cents": o.requirement_min_cents
        if o.requirement_min_cents is not None
        else o.requirement_max_cents,
        "window_count": o.qualification_window_count,
        "window_unit": o.qualification_window_unit,
        "window_start": start,
        "window_text": o.qualification_window_text,
        "cap_text": None,
        "categories": [],
        "annual_fee_cents": card.annual_fee_cents if card is not None else None,
        "first_year_fee_cents": first_year,
        "start": deadline.moment(o.verbatim_text, deadline._START_CUE) if o.start_date else None,
        "end": deadline.end_from_offer(o.verbatim_text, o.expiration_date, o.open_by_date),
        "eligibility_text": norm(o.eligibility_restrictions),
        "channels_seen": sorted({str(e.get("channel")) for e in o.seen_on or [] if e.get("channel")}),
        "verbatim": norm(o.verbatim_text),
        # the page address without query parameters (some issuers redirect to tracking parameters)
        "offer_url": o.offer_url.split("?", 1)[0],
    }


def structure(t: dict[str, Any]) -> str:
    """The reward structure part of the identity: unit, number of tiers and what must be done."""
    return f"{t.get('unit')}:{len(t.get('tiers') or [])}:{t.get('requirement_type') or 'none'}"


def campaign_key(card_key: str, t: dict[str, Any]) -> str:
    return f"{card_key}|{t['channel']}|{t['offer_type']}|{structure(t)}"


def material(t: dict[str, Any]) -> dict[str, Any]:
    out = {k: t.get(k) for k in MATERIAL}
    # a tier's terms only: display labels (unit_name) and wording (text) are not terms, and an absent "incremental"
    # means not incremental — so the same offer read by an adapter or entered by hand hashes the same
    out["tiers"] = [
        {k: (bool(tier.get(k)) if k == "incremental" else tier.get(k)) for k in TIER_TERMS}
        for tier in t.get("tiers") or []
    ]
    # absent and empty are the same: offers read before these fields existed must hash as they did
    out["offer_components"] = [
        {k: v for k, v in c.items() if k != "text"} for c in t.get("offer_components") or []
    ] or None
    for k in ("start", "end"):
        m = out.get(k)
        out[k] = {f: m.get(f) for f in ("date", "time", "time_known")} if m else None
    return out


def material_hash(t: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(material(t), sort_keys=True, default=str).encode()).hexdigest()  # noqa: S324


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = material(old), material(new)
    return [{"field": k, "old": a.get(k), "new": b.get(k)} for k in MATERIAL if a.get(k) != b.get(k)]


def filter_columns(t: dict[str, Any]) -> dict[str, Any]:
    end = t.get("end") or {}
    return {
        "reward_amount": t.get("total_amount"),
        "reward_unit": t.get("unit"),
        "min_spend_cents": t.get("min_spend_cents"),
        "end_date": datetime.fromisoformat(end["date"]).date() if end.get("date") else None,
    }
