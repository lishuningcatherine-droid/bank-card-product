"""Apply licensed-provider records: lowest priority, never overrides official values, labeled, and capped at
Partially verified (provider-only fields)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.ingest.providers.base import ProviderConfig, ProviderRecord, check_gate
from bankrec.publish.changes import jsonable
from bankrec.publish.publisher import enqueue_revalidation, product_tags

DETAIL = {"credit_card": "card", "checking": "checking", "savings": "savings"}


def apply_records(session: Session, cfg: ProviderConfig, records: list[ProviderRecord], now: datetime) -> dict[str, int]:
    check_gate(cfg)
    stats = {"filled": 0, "conflicts": 0, "skipped": 0}
    for r in records:
        session.add(S.ProviderRecord(provider_id=cfg.provider_id, external_id=r.external_id,
                                     fields=jsonable(r.fields), as_of=r.as_of))
        p = session.scalar(select(P.Product).where(P.Product.bank_id == r.bank_id,
                                                   P.Product.product_type == r.product_type,
                                                   P.Product.official_name == r.product_name))
        if p is None or not cfg.license.display_permitted:
            stats["skipped"] += 1
            continue
        detail = getattr(p, DETAIL[p.product_type])
        for k, v in r.fields.items():
            if not hasattr(detail, k):
                continue
            current: Any = getattr(detail, k)
            if current is None:
                setattr(detail, k, v)
                p.provider_only_fields = sorted({*p.provider_only_fields, k})
                session.add(P.FieldProvenance(product_id=p.id, field_path=k, provenance_class="licensed_provider",
                                              source_id=f"provider:{cfg.provider_id}",
                                              span_text=cfg.license.attribution_text, parser_name=cfg.provider_id,
                                              parser_version="provider", retrieved_at=r.as_of,
                                              last_confirmed_at=r.as_of))
                stats["filled"] += 1
            elif jsonable(current) != jsonable(v):
                session.add(S.ManualReviewItem(item_kind="provider_conflict", reason_code="provider_conflict",
                                               bank_id=p.bank_id, product_type=p.product_type,
                                               canonical_key=p.canonical_key,
                                               context={"field": k, "official": jsonable(current),
                                                        "provider": jsonable(v), "provider_id": cfg.provider_id},
                                               created_at=now))
                stats["conflicts"] += 1
        enqueue_revalidation(session, product_tags(p), now)
    return stats
