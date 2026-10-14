"""Canonical product identity (brief §8). URL is never part of identity."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

_STOP = re.compile(r"\b(?:the|credit card|card|checking account|savings account|account)\b")


def norm_name(name: str, bank_display_name: str | None = None) -> str:
    s = unicodedata.normalize("NFKC", name).lower()
    s = re.sub(r"[®™℠©*†‡]", "", s)
    if bank_display_name:
        s = re.sub(r"\bfrom\s+" + re.escape(bank_display_name.lower()) + r"\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(?:checking|savings)\b(?=.*\b(?:checking|savings)\b)", " ", s)  # collapse duplicates
    s = _STOP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_key(
    bank_id: str,
    product_type: str,
    segment: str | None,
    name: str,
    variant: str | None = None,
    bank_display_name: str | None = None,
) -> str:
    seg = segment or ("consumer" if product_type == "credit_card" else "personal")
    var = norm_name(variant) if variant else "-"
    return f"{bank_id}:{product_type}:{seg}:{norm_name(name, bank_display_name)}:{var}"


def _window_identity(o: dict[str, Any]) -> int | None:
    """The window's part of the offer identity. Kept equal to the identity used before windows kept their stated
    unit (a "3 months" window was keyed as 90), so the same offer keeps its key; an identity hash only, never a
    stored value."""
    if o.get("qualification_window_days") is not None:
        return int(o["qualification_window_days"])
    n, unit = o.get("qualification_window_count"), o.get("qualification_window_unit")
    if n is None:
        return None
    return {"months": n * 30, "weeks": n * 7, "years": n * 365}.get(str(unit))


def offer_key(product_key: str, o: dict[str, Any]) -> str:
    parts = [
        product_key,
        o.get("offer_type"),
        o.get("amount_qualifier"),
        o.get("amount_min"),
        o.get("amount_max"),
        o.get("reward_unit"),
        o.get("requirement_type"),
        o.get("requirement_min_cents"),
        o.get("requirement_max_cents"),
        _window_identity(o),
        o.get("audience"),
        tuple(t.get("amount") for t in o.get("tiers") or []),
    ]
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:20]  # noqa: S324 (identity hash, not security)
