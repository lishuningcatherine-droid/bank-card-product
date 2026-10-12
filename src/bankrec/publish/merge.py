"""Merge candidates for one canonical product across sources, by source priority (brief §7.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bankrec.candidate import ProductCandidate
from bankrec.model import PRIORITY, BenefitRec, OfferRec, RewardRateRec, Sourced
from bankrec.publish.changes import jsonable


@dataclass
class Meta:
    source_id: str
    snapshot_id: str | None
    url: str
    parser_name: str
    parser_version: str
    retrieved_at: datetime
    priority: int
    capture_conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class MergedOffer:
    rec: OfferRec
    span: Sourced[OfferRec]
    meta: Meta
    status: str  # valid | needs_review | reject


@dataclass
class MergedProduct:
    canonical_key: str
    bank_id: str
    product_type: str
    primary: ProductCandidate
    primary_meta: Meta
    fields: dict[str, tuple[Sourced[Any], Meta]] = field(default_factory=dict)
    reward_rates: list[tuple[Sourced[RewardRateRec], Meta]] = field(default_factory=list)
    benefits: list[tuple[Sourced[BenefitRec], Meta]] = field(default_factory=list)
    offers: list[MergedOffer] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)
    offer_absent_note: str | None = None

    def value(self, name: str) -> Any:
        f = self.fields.get(name)
        return f[0].value if f else None

    @property
    def name(self) -> str:
        return str(self.value("official_name"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "fields": {k: jsonable(s.value) for k, (s, _) in sorted(self.fields.items())},
            "reward_rates": [jsonable(s.value) for s, _ in self.reward_rates],
            "benefits": [jsonable(s.value) for s, _ in self.benefits],
        }


def merge(cands: list[tuple[ProductCandidate, Meta]], canonical_key: str) -> MergedProduct:
    ordered = sorted(cands, key=lambda cm: (-cm[1].priority, cm[1].source_id))
    primary, pmeta = ordered[0]
    mp = MergedProduct(
        canonical_key,
        primary.bank_id,
        primary.product_type.value,
        primary,
        pmeta,
        offer_absent_note=primary.offer_absent_note,
    )
    for c, meta in ordered:
        if c.name:
            mp.aliases.add(c.name)
        for k, s in c.fields.items():
            cur = mp.fields.get(k)
            if cur is None or (not cur[0].present and s.present):
                mp.fields[k] = (s, meta)
            elif s.present and cur[0].present and jsonable(s.value) != jsonable(cur[0].value):
                mp.conflicts.append(
                    {
                        "field": k,
                        "values": [
                            {"value": jsonable(cur[0].value), "source": cur[1].source_id, "url": cur[1].url},
                            {"value": jsonable(s.value), "source": meta.source_id, "url": meta.url},
                        ],
                    }
                )
        if not mp.reward_rates and c.reward_rates:
            mp.reward_rates = [(r, meta) for r in c.reward_rates]
        if not mp.benefits and c.benefits:
            mp.benefits = [(b, meta) for b in c.benefits]
        if c.offer_absent_note and not mp.offer_absent_note:
            mp.offer_absent_note = c.offer_absent_note
    return mp


def meta_priority(page_type: Any) -> int:
    return PRIORITY.get(page_type, 0)
