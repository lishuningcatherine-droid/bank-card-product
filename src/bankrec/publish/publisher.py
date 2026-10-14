"""Publish merged records to ``prod`` with versioning, provenance, and revalidation outbox (DESIGN §9, §21)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.dedup.canonical import offer_key
from bankrec.model import Sourced
from bankrec.publish.changes import Change, jsonable
from bankrec.publish.merge import MergedOffer, MergedProduct, Meta
from bankrec.registry.schema import BankConfig

DETAIL_MODEL = {
    "credit_card": P.CreditCardDetails,
    "checking": P.CheckingAccountDetails,
    "savings": P.SavingsAccountDetails,
}
DETAIL_ATTR = {"credit_card": "card", "checking": "checking", "savings": "savings"}
OFFER_COLUMNS = [
    c.name
    for c in P.Offer.__table__.columns
    if c.name
    not in {
        "id",
        "offer_key",
        "product_id",
        "capture_conditions",
        "retrieved_at",
        "verified_at",
        "last_confirmed_at",
        "last_changed_at",
        "status",
        "recheck_reason",
        "current_version",
        "tiers",
    }
]


def enqueue_revalidation(
    session: Session, tags: list[str], now: datetime, not_before: datetime | None = None
) -> None:
    session.add(S.RevalidationOutbox(tags=sorted(set(tags)), created_at=now, not_before=not_before))


def product_tags(product: P.Product) -> list[str]:
    return [
        f"product:{product.id}",
        f"listing:{product.product_type}",
        "listing:all",
        f"bank:{product.bank_id}",
        "sources",
    ]


def upsert_bank(session: Session, bank: BankConfig) -> None:
    row = session.get(P.Bank, bank.bank_id)
    avail = {k.value: v.model_dump(mode="json") for k, v in bank.product_types.items()}
    if row is None:
        session.add(
            P.Bank(
                bank_id=bank.bank_id,
                display_name=bank.display_name,
                official_domains=bank.official_domains,
                product_type_availability=avail,
                test_only=bank.test_only,
                known_limitations=bank.known_limitations,
            )
        )
    else:
        row.display_name, row.official_domains = bank.display_name, bank.official_domains
        row.product_type_availability, row.test_only = avail, bank.test_only
        row.known_limitations = bank.known_limitations
    session.flush()


def upsert_categories(session: Session) -> None:
    from bankrec.normalize.categories import vocabulary

    for code, spec in vocabulary().items():
        row = session.get(P.RewardCategory, code)
        if row is None:
            session.add(P.RewardCategory(code=code, label=str(spec["label"])))
        else:
            row.label = str(spec["label"])
    session.flush()


def _detail_values(mp: MergedProduct) -> dict[str, Any]:
    model = DETAIL_MODEL[mp.product_type]
    cols = set(model.__table__.columns.keys()) - {"product_id"}
    out: dict[str, Any] = {}
    for k in cols:
        v = mp.value(k)
        if k in {"fee_waivers", "apy_tiers"} and v is not None:
            v = jsonable(v)
        out[k] = v
    if mp.product_type == "credit_card":
        for flag in ("is_co_branded", "is_student", "is_secured"):
            out[flag] = bool(out.get(flag))
    return out


def _write_children(session: Session, product: P.Product, mp: MergedProduct) -> None:
    product.reward_rates.clear()
    product.benefits.clear()
    session.flush()
    for s, _ in mp.reward_rates:
        r = s.value
        assert r is not None
        product.reward_rates.append(
            P.ProductRewardRate(
                category=r.category,
                rate=r.rate,
                rate_unit=r.rate_unit,
                cap_cents=r.cap_cents,
                cap_period=r.cap_period,
                cap_combined=r.cap_combined,
                cap_group=r.cap_group,
                post_cap_rate=r.post_cap_rate,
                is_rotating=r.is_rotating,
                requires_activation=r.requires_activation,
                portal_only=r.portal_only,
                ends_on=r.ends_on,
                conditions_text=r.text,
                conditions=[c.model_dump() for c in r.conditions],
            )
        )
    for sb, _ in mp.benefits:
        b = sb.value
        assert b is not None
        product.benefits.append(
            P.ProductBenefit(
                benefit_type=b.benefit_type,
                name=b.name,
                monetizable=b.monetizable,
                amount_cents=b.amount_cents,
                period=b.period,
                period_years=b.period_years,
                merchant_restriction=b.merchant_restriction,
                enrollment_required=b.enrollment_required,
                conditions_text=b.text,
            )
        )


def _write_provenance(session: Session, product: P.Product, mp: MergedProduct, now: datetime) -> None:
    session.query(P.FieldProvenance).filter(
        P.FieldProvenance.product_id == product.id, P.FieldProvenance.offer_id.is_(None)
    ).delete()
    for name, (s, meta) in mp.fields.items():
        session.add(
            P.FieldProvenance(
                product_id=product.id,
                field_path=name,
                null_reason=s.null_reason.value if s.null_reason else None,
                snapshot_id=meta.snapshot_id,
                source_id=meta.source_id,
                source_url=meta.url,
                span_text=s.span_text,
                parser_name=meta.parser_name,
                parser_version=meta.parser_version,
                provenance_class=s.provenance_class.value,
                retrieved_at=meta.retrieved_at,
                last_confirmed_at=now,
            )
        )
    children: list[tuple[str, list[tuple[Sourced[Any], Meta]]]] = [
        ("reward_rates", list(mp.reward_rates)),
        ("benefits", list(mp.benefits)),
    ]
    for kind, items in children:
        for i, (s, meta) in enumerate(items):
            session.add(
                P.FieldProvenance(
                    product_id=product.id,
                    field_path=f"{kind}[{i}]",
                    snapshot_id=meta.snapshot_id,
                    source_id=meta.source_id,
                    source_url=meta.url,
                    span_text=s.span_text,
                    parser_name=meta.parser_name,
                    parser_version=meta.parser_version,
                    provenance_class=s.provenance_class.value,
                    retrieved_at=meta.retrieved_at,
                    last_confirmed_at=now,
                )
            )


def publish_product(
    session: Session,
    mp: MergedProduct,
    bank: BankConfig,
    *,
    run_id: str,
    now: datetime,
    missing_fields: list[str],
    critical_missing: list[str],
    changes: list[Change] | None,
    existing: P.Product | None,
) -> P.Product:
    """Create (initial version) or update (new version) a product from a validated merged record."""
    snap = mp.snapshot()
    if existing is None:
        product = P.Product(
            id=uuid.uuid4(),
            canonical_key=mp.canonical_key,
            bank_id=mp.bank_id,
            product_type=mp.product_type,
            official_name=mp.name,
            product_family=mp.value("product_family"),
            variant=mp.value("variant"),
            official_url=mp.primary_meta.url,
            terms_url=mp.value("terms_url"),
            retrieved_at=mp.primary_meta.retrieved_at,
            verified_at=now,
            first_published_at=now,
            last_confirmed_at=now,
            last_checked_at=now,
            last_changed_at=None,
            apy_confirmed_at=now if mp.product_type == "savings" else None,
            missing_fields=missing_fields,
            critical_missing=critical_missing,
            test_only=bank.test_only,
            offer_absent_note=mp.offer_absent_note,
            offer_status=mp.offer_status,
            current_version=1,
        )
        session.add(product)
        session.flush()
        setattr(product, DETAIL_ATTR[mp.product_type], DETAIL_MODEL[mp.product_type](**_detail_values(mp)))
        session.add(
            P.ProductVersion(
                product_id=product.id,
                version=1,
                snapshot=snap,
                change_summary=[],
                change_class="initial",
                valid_from=now,
                run_id=run_id,
                source_url=mp.primary_meta.url,
            )
        )
    else:
        product = existing
        detail = getattr(product, DETAIL_ATTR[mp.product_type])
        for k, v in _detail_values(mp).items():
            setattr(detail, k, v)
        product.official_name, product.terms_url = mp.name, mp.value("terms_url")
        product.official_url, product.retrieved_at = mp.primary_meta.url, mp.primary_meta.retrieved_at
        product.verified_at = product.last_confirmed_at = product.last_checked_at = now
        if mp.product_type == "savings":
            product.apy_confirmed_at = now
        product.missing_fields, product.critical_missing = missing_fields, critical_missing
        product.offer_absent_note = mp.offer_absent_note
        product.offer_status = mp.offer_status
        product.recheck_pending, product.recheck_reason, product.recheck_fields = False, None, []
        material = [c for c in changes or [] if c.change_class != "info"]
        if material:
            product.last_changed_at = now
        session.execute(
            update(P.ProductVersion)
            .where(P.ProductVersion.product_id == product.id, P.ProductVersion.valid_to.is_(None))
            .values(valid_to=now)
        )
        product.current_version += 1
        session.add(
            P.ProductVersion(
                product_id=product.id,
                version=product.current_version,
                snapshot=snap,
                change_summary=[
                    {
                        "field": c.field,
                        "old": jsonable(c.old),
                        "new": jsonable(c.new),
                        "class": c.change_class,
                    }
                    for c in changes or []
                ],
                change_class=("major" if any(c.change_class == "major" for c in changes or []) else "minor"),
                valid_from=now,
                run_id=run_id,
                source_url=mp.primary_meta.url,
            )
        )
    session.flush()
    product.aliases.clear()
    for a in sorted(mp.aliases - {mp.name}):
        product.aliases.append(P.ProductAlias(alias=a))
    _write_children(session, product, mp)
    _write_provenance(session, product, mp, now)
    enqueue_revalidation(session, product_tags(product), now)
    return product


def offer_values(o: MergedOffer) -> dict[str, Any]:
    d = o.rec.model_dump()
    return {k: d.get(k) for k in OFFER_COLUMNS}


def publish_offer(
    session: Session,
    product: P.Product,
    o: MergedOffer,
    *,
    run_id: str,
    now: datetime,
    change_class: str = "initial",
) -> P.Offer:
    key = offer_key(product.canonical_key, jsonable(o.rec.model_dump()))
    row = session.scalar(select(P.Offer).where(P.Offer.offer_key == key))
    snap = jsonable(o.rec.model_dump())
    if row is None:
        row = P.Offer(
            id=uuid.uuid4(),
            offer_key=key,
            product_id=product.id,
            **offer_values(o),
            tiers=jsonable([t.model_dump() for t in o.rec.tiers]),
            capture_conditions=o.meta.capture_conditions,
            retrieved_at=o.meta.retrieved_at,
            verified_at=now,
            last_confirmed_at=now,
            last_changed_at=None,
            status="current",
            current_version=1,
        )
        session.add(row)
        session.flush()
        session.add(
            P.OfferVersion(
                offer_id=row.id,
                product_id=product.id,
                version=1,
                snapshot=snap,
                change_summary=[],
                change_class=change_class,
                valid_from=now,
                run_id=run_id,
            )
        )
    else:
        row.verified_at = row.last_confirmed_at = now
        row.status, row.recheck_reason = "current", None
        row.capture_conditions = o.meta.capture_conditions
        # Same offer (same key): descriptive columns follow the current reading, so a representation fix (e.g. a
        # window kept in its stated unit) reaches existing rows without a new offer version.
        for k, v in offer_values(o).items():
            setattr(row, k, v)
        row.tiers = jsonable([t.model_dump() for t in o.rec.tiers])
    session.add(
        P.FieldProvenance(
            product_id=product.id,
            offer_id=row.id,
            field_path="offer",
            snapshot_id=o.meta.snapshot_id,
            source_id=o.meta.source_id,
            source_url=o.meta.url,
            span_text=o.span.span_text,
            parser_name=o.meta.parser_name,
            parser_version=o.meta.parser_version,
            provenance_class=o.span.provenance_class.value,
            retrieved_at=o.meta.retrieved_at,
            last_confirmed_at=now,
        )
    )
    enqueue_revalidation(session, product_tags(product), now)
    if o.rec.expiration_date is not None:
        from bankrec.publish.timing import expiry_instant

        enqueue_revalidation(
            session, product_tags(product), now, not_before=expiry_instant(o.rec.expiration_date)
        )
    return row


def retire_offer(session: Session, offer: P.Offer, *, status: str, reason: str, now: datetime) -> None:
    offer.status, offer.recheck_reason = status, reason
    session.execute(
        update(P.OfferVersion)
        .where(P.OfferVersion.offer_id == offer.id, P.OfferVersion.valid_to.is_(None))
        .values(valid_to=now)
    )
    offer.current_version += 1
    session.add(
        P.OfferVersion(
            offer_id=offer.id,
            product_id=offer.product_id,
            version=offer.current_version,
            snapshot={"status": status, "reason": reason},
            change_summary=[{"field": "status", "old": "current", "new": status, "class": "major"}],
            change_class="major",
            valid_from=now,
        )
    )
