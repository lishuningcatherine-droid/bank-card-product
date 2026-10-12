"""Fuzzy duplicate detection. Never merges or deletes; proposes review items (brief §8)."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

THRESHOLD = 85


@dataclass
class DupProposal:
    a: str
    b: str
    reason: str
    similarity: float
    proposed: str | None  # proposed canonical key, or None when proposing "distinct"
    decision: str  # auto | manual


@dataclass
class KeyInfo:
    key: str
    bank_id: str
    product_type: str
    name: str  # normalized name
    segment: str
    annual_fee_cents: int | None = None
    co_brand_partner: str | None = None


def _distinct_reason(a: KeyInfo, b: KeyInfo) -> str | None:
    if a.segment != b.segment:
        return "segment differs"
    if a.annual_fee_cents is not None and b.annual_fee_cents is not None and a.annual_fee_cents != b.annual_fee_cents:
        return "annual fee differs"
    tiers = {"plus", "premier", "preferred", "reserve", "select", "platinum", "gold", "elite", "infinite", "signature",
             "unlimited", "flex", "one", "savor", "savorone", "venture", "venturex", "ventureone", "business"}
    ta, tb = set(a.name.split()) & tiers, set(b.name.split()) & tiers
    if ta != tb:
        return f"variant words differ ({sorted(ta ^ tb)})"
    return None


def _strip_bank(name: str, bank_id: str) -> str:
    """Remove the bank's own name tokens so a shared "<Bank> ..." prefix does not inflate similarity."""
    drop = set(bank_id.split("_")) | {"of", "the", "n", "a"}
    return " ".join(t for t in name.split() if t not in drop)


def find_fuzzy(keys: list[KeyInfo]) -> list[DupProposal]:
    out: list[DupProposal] = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a.key == b.key or (a.bank_id, a.product_type) != (b.bank_id, b.product_type):
                continue
            na, nb = _strip_bank(a.name, a.bank_id), _strip_bank(b.name, b.bank_id)
            if not na or not nb:
                continue
            sim = fuzz.token_set_ratio(na, nb)
            prefix = na.startswith(nb) or nb.startswith(na)
            if sim < THRESHOLD and not prefix:
                continue
            distinct = _distinct_reason(a, b)
            reason = f"token_set_ratio={sim:.0f}" + (" prefix" if prefix else "")
            if distinct:
                reason += f"; proposed distinct: {distinct}"
            out.append(DupProposal(a.key, b.key, reason, round(sim / 100, 4),
                                   None if distinct else min(a.key, b.key), "manual"))
    return out
