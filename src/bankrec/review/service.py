"""Manual review workflow (brief §7.5). Every decision is written to review_decisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.candidate import ProductCandidate
from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.ingest.pipeline import rehydrate
from bankrec.model import ExtractionContext, NullReason, PageType, ProvenanceClass, Sourced
from bankrec.publish.changes import diff_product, jsonable
from bankrec.publish.merge import MergedOffer, Meta, merge, meta_priority
from bankrec.publish.publisher import enqueue_revalidation, product_tags, publish_offer, publish_product
from bankrec.registry.loader import Registry
from bankrec.validation.rules import policy, validate


class ReviewError(Exception):
    pass


def _item(session: Session, item_id: int) -> S.ManualReviewItem:
    it = session.get(S.ManualReviewItem, item_id)
    if it is None:
        raise ReviewError(f"review item {item_id} not found")
    return it


def _log(
    session: Session,
    it: S.ManualReviewItem,
    action: str,
    reviewer: str,
    note: str | None,
    now: datetime,
    payload: dict[str, Any] | None = None,
) -> None:
    if not reviewer:
        raise ReviewError("a reviewer name is required (--reviewer or BANKREC_REVIEWER)")
    session.add(
        S.ReviewDecision(
            queue_id=it.id,
            action=action,
            reviewer=reviewer,
            decided_at=now,
            note=note,
            payload=jsonable(payload or {}),
        )
    )


def list_items(
    session: Session, *, product_type: str | None = None, bank: str | None = None, state: str = "open"
) -> list[S.ManualReviewItem]:
    q = select(S.ManualReviewItem).where(S.ManualReviewItem.state == state).order_by(S.ManualReviewItem.id)
    if product_type:
        q = q.where(S.ManualReviewItem.product_type == product_type)
    if bank:
        q = q.where(S.ManualReviewItem.bank_id == bank)
    return list(session.scalars(q))


def _candidates(
    session: Session, it: S.ManualReviewItem
) -> list[tuple[ProductCandidate, Meta, S.ExtractionCandidate]]:
    out = []
    for cid in (it.context or {}).get("candidate_ids", []):
        row = session.get(S.ExtractionCandidate, uuid.UUID(cid))
        if row is None:
            continue
        c = rehydrate(ProductCandidate.model_validate(row.payload))
        snap = session.get(S.PageSnapshot, row.snapshot_id) if row.snapshot_id else None
        meta = Meta(
            row.source_id,
            row.snapshot_id,
            c.url,
            row.parser_name,
            row.parser_version,
            c.retrieved_at,
            meta_priority(c.page_type),
            snap.capture_conditions if snap else {},
        )
        out.append((c, meta, row))
    return out


def show(session: Session, item_id: int) -> dict[str, Any]:
    it = _item(session, item_id)
    out: dict[str, Any] = {
        "id": it.id,
        "kind": it.item_kind,
        "reason": it.reason_code,
        "state": it.state,
        "canonical_key": it.canonical_key,
        "context": it.context,
        "candidates": [],
    }
    for c, meta, row in _candidates(session, it):
        snap = session.get(S.PageSnapshot, row.snapshot_id) if row.snapshot_id else None
        excerpt = ""
        if snap and Path(snap.text_path).exists():
            excerpt = Path(snap.text_path).read_text(encoding="utf-8")[:1500]
        out["candidates"].append(
            {
                "source_id": meta.source_id,
                "url": meta.url,
                "status": row.status,
                "page_type": c.page_type.value,
                "values": {k: jsonable(v.value) for k, v in c.fields.items() if v.present},
                "evidence": {k: v.span_text for k, v in c.fields.items() if v.present},
                "offers": [jsonable(o.value) for o in c.offers],
                "snapshot_excerpt": excerpt,
            }
        )
    dups = session.scalars(
        select(S.DuplicateCandidate).where(
            (S.DuplicateCandidate.a == it.canonical_key) | (S.DuplicateCandidate.b == it.canonical_key)
        )
    )
    out["dedup_proposals"] = [
        {"a": d.a, "b": d.b, "reason": d.reason, "proposed": d.proposed_canonical} for d in dups
    ]
    return out


def approve(
    session: Session,
    registry: Registry,
    item_id: int,
    *,
    reviewer: str,
    note: str | None,
    now: datetime,
    run_id: str = "review",
) -> str:
    it = _item(session, item_id)
    if it.state != "open" and it.state != "edited":
        raise ReviewError(f"item {item_id} is {it.state}")
    result = "acknowledged"
    if it.item_kind in {"product", "offer"}:
        cands = _candidates(session, it)
        if not cands:
            raise ReviewError("no candidates attached to this item")
        mp = merge([(c, m) for c, m, _ in cands], it.canonical_key or "")
        bank = registry.bank(mp.bank_id)
        existing = session.scalar(select(P.Product).where(P.Product.canonical_key == mp.canonical_key))
        c0 = cands[0][0]
        pol = policy()
        missing_key = [
            f
            for f in pol["key"][c0.product_type.value]
            if not (
                c0.fields.get(f)
                and (c0.fields[f].present or c0.fields[f].null_reason is NullReason.not_applicable)
            )
        ]
        if it.item_kind == "product" or existing is None:
            changes = None
            if existing is not None:
                old = session.scalar(
                    select(P.ProductVersion.snapshot).where(
                        P.ProductVersion.product_id == existing.id, P.ProductVersion.valid_to.is_(None)
                    )
                )
                changes = diff_product(old or {}, mp.snapshot())
            product = publish_product(
                session,
                mp,
                bank,
                run_id=run_id,
                now=now,
                missing_fields=c0.missing_fields,
                critical_missing=missing_key,
                changes=changes,
                existing=existing,
            )
            result = "published"
        else:
            product = existing
        for c, meta, _ in cands:
            snap = session.get(S.PageSnapshot, meta.snapshot_id) if meta.snapshot_id else None
            text = Path(snap.text_path).read_text(encoding="utf-8") if snap is not None else ""
            v = validate(c, text, bank.official_domains)
            for ov in v.offers:
                if ov.status != "reject":
                    so = c.offers[ov.index]
                    assert so.value is not None
                    publish_offer(
                        session, product, MergedOffer(so.value, so, meta, "valid"), run_id=run_id, now=now
                    )
        for o in product.offers:
            if o.status == "recheck_pending" and o.recheck_reason in {"offer_disappeared", "offer_changed"}:
                o.status = "expired" if o.recheck_reason == "offer_disappeared" else "uncertain"
        enqueue_revalidation(session, product_tags(product), now)
    elif it.item_kind == "duplicate":
        result = "accepted_distinct"
    it.state = "approved"
    _log(session, it, "approve", reviewer, note, now, {"result": result})
    return result


def reject(session: Session, item_id: int, *, reviewer: str, reason: str, now: datetime) -> None:
    it = _item(session, item_id)
    it.state = "rejected"
    if it.canonical_key and it.item_kind == "product":
        p = session.scalar(select(P.Product).where(P.Product.canonical_key == it.canonical_key))
        if p is not None and it.reason_code == "major_change":
            # Old value stays; the extraction was wrong. Keep recheck flag until a good parse confirms it.
            p.recheck_reason = "extraction_rejected"
    _log(session, it, "reject", reviewer, reason, now)


def merge_products(
    session: Session, a_key: str, b_key: str, *, reviewer: str, note: str | None, now: datetime
) -> None:
    """Manual merge: B's names become aliases of A; B is withdrawn (kept, never deleted)."""
    a = session.scalar(select(P.Product).where(P.Product.canonical_key == a_key))
    b = session.scalar(select(P.Product).where(P.Product.canonical_key == b_key))
    if a is None or b is None:
        raise ReviewError("both products must be published to merge")
    a.aliases.append(P.ProductAlias(alias=b.official_name))
    b.status = "withdrawn"
    for d in session.scalars(
        select(S.DuplicateCandidate).where(
            S.DuplicateCandidate.a.in_([a_key, b_key]), S.DuplicateCandidate.b.in_([a_key, b_key])
        )
    ):
        d.final_result = f"merged into {a_key}"
    items = session.scalars(
        select(S.ManualReviewItem).where(
            S.ManualReviewItem.canonical_key.in_([f"{a_key}|{b_key}", f"{b_key}|{a_key}"])
        )
    )
    logged = False
    for it in items:
        it.state = "merged"
        _log(session, it, "merge", reviewer, note, now, {"a": a_key, "b": b_key})
        logged = True
    if not logged:
        it = S.ManualReviewItem(
            item_kind="duplicate",
            reason_code="manual_merge",
            canonical_key=f"{a_key}|{b_key}",
            context={"a": a_key, "b": b_key},
            state="merged",
            created_at=now,
        )
        session.add(it)
        session.flush()
        _log(session, it, "merge", reviewer, note, now, {"a": a_key, "b": b_key})
    enqueue_revalidation(session, product_tags(a) + product_tags(b), now)


def edit(
    session: Session, item_id: int, *, field: str, value: Any, evidence: str, reviewer: str, now: datetime
) -> None:
    """Set a field value; the quoted evidence must exist in a stored snapshot of this item's candidates."""
    it = _item(session, item_id)
    cands = _candidates(session, it)
    for c, meta, row in cands:
        snap = session.get(S.PageSnapshot, meta.snapshot_id) if meta.snapshot_id else None
        if snap is None or not Path(snap.text_path).exists():
            continue
        ctx = ExtractionContext(
            Path(snap.text_path).read_text(encoding="utf-8"), 1.0, ProvenanceClass.official_page
        )
        s = ctx.field(value, evidence, method="manual_review", name=field)
        if s.present:
            c.fields[field] = Sourced(**{**s.model_dump(), "value": value})
            row.payload = c.model_dump(mode="json")
            it.state = "edited"
            _log(
                session,
                it,
                "edit",
                reviewer,
                f"{field}={value!r}",
                now,
                {"field": field, "value": value, "evidence": evidence},
            )
            return
    raise ReviewError("evidence text was not found in any stored snapshot for this item; edit refused")


__all__ = ["PageType", "ReviewError", "approve", "edit", "list_items", "merge_products", "reject", "show"]
