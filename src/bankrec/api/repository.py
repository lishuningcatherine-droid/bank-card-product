"""Read-only access to ``prod`` for the API and the recommender. Labels and offer states are computed at request
time; Under-review and test-only records are never returned (test-only only in E2E test mode)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from bankrec.db import prod as P
from bankrec.freshness import offer_state, product_label
from bankrec.publish.changes import jsonable
from bankrec.recommend.models import BenefitView, OfferView, ProductView, RateView

__all__ = ["Filters", "Repository", "to_view"]

DETAIL = {"credit_card": "card", "checking": "checking", "savings": "savings"}


@dataclass
class Filters:
    type: str | None = None
    bank: str | None = None
    annual_fee_max: int | None = None  # dollars
    reward_category: str | None = None
    has_bonus: bool | None = None
    apy_min: Decimal | None = None
    verified_since: datetime | None = None
    segment: str | None = None
    card_flags: list[str] | None = None
    q: str | None = None


def _detail_dict(p: P.Product) -> dict[str, Any]:
    d = getattr(p, DETAIL[p.product_type])
    if d is None:
        return {}
    out = {c.name: getattr(d, c.name) for c in d.__table__.columns if c.name != "product_id"}
    for k, v in list(out.items()):
        if isinstance(v, Decimal):
            out[k] = v.normalize() if v == v.to_integral() else v
    return out


def to_view(p: P.Product, now: datetime, bank_name: str) -> ProductView:
    label, reasons = product_label(
        published=True,
        terms_confirmed_at=p.last_confirmed_at,
        apy_confirmed_at=p.apy_confirmed_at,
        product_type=p.product_type,
        missing_key=list(p.critical_missing or []),
        recheck_pending=p.recheck_pending,
        provider_only_fields=list(p.provider_only_fields or []),
        now=now,
    )
    offers = []
    for o in p.offers:
        st = offer_state(o.status, o.expiration_date, o.last_confirmed_at, now, o.audience)
        if st in {"targeted"}:
            continue  # targeted offers are never shown as generally available
        offers.append(
            OfferView(
                id=str(o.id),
                offer_type=o.offer_type,
                reward_unit=o.reward_unit,
                amount_qualifier=o.amount_qualifier,
                amount_min=o.amount_min,
                amount_max=o.amount_max,
                requirement_type=o.requirement_type,
                requirement_qualifier=o.requirement_qualifier,
                requirement_min_cents=o.requirement_min_cents,
                requirement_max_cents=o.requirement_max_cents,
                required_dd_count=o.required_dd_count,
                qualification_window_days=o.qualification_window_days,
                qualification_window_months=o.qualification_window_months,
                qualification_window_count=o.qualification_window_count,
                qualification_window_unit=o.qualification_window_unit,
                holding_period_days=o.holding_period_days,
                holding_period_count=o.holding_period_count,
                holding_period_unit=o.holding_period_unit,
                expiration_date=o.expiration_date,
                tiers=list(o.tiers or []),
                offer_url=o.offer_url,
                verified_at=o.verified_at,
                last_confirmed_at=o.last_confirmed_at,
                state=st,
                verbatim_text=o.verbatim_text,
                note=o.note,
                eligibility_restrictions=o.eligibility_restrictions,
            )
        )
    rates = [
        RateView(
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
            text=r.conditions_text,
        )
        for r in p.reward_rates
    ]
    benefits = []
    for b in p.benefits:
        mult = {"monthly": 12, "quarterly": 4, "semiannual": 2, "annual": 1}.get(b.period or "")
        annual = (
            (
                b.amount_cents * mult
                if mult and b.amount_cents is not None
                else b.amount_cents // b.period_years
                if b.period == "multi_year" and b.period_years and b.amount_cents
                else None
            )
            if b.monetizable
            else None
        )
        benefits.append(
            BenefitView(
                id=str(b.id),
                benefit_type=b.benefit_type,
                name=b.name,
                monetizable=b.monetizable,
                amount_cents=b.amount_cents,
                period=b.period,
                period_years=b.period_years,
                annual_value_cents=annual,
                enrollment_required=b.enrollment_required,
                merchant_restriction=b.merchant_restriction,
            )
        )
    return ProductView(
        id=str(p.id),
        bank_id=p.bank_id,
        bank_name=bank_name,
        product_type=p.product_type,
        name=p.official_name,
        official_url=p.official_url,
        terms_url=p.terms_url,
        label=label if label != "under_review" else "partially_verified",
        label_reasons=reasons,
        verified_at=p.last_confirmed_at,
        last_checked_at=p.last_checked_at,
        last_changed_at=p.last_changed_at,
        first_published_at=p.first_published_at,
        recheck_pending=p.recheck_pending,
        missing_fields=list(p.critical_missing or []),
        provider_only_fields=list(p.provider_only_fields or []),
        details=jsonable(_detail_dict(p)) | {k: v for k, v in _detail_dict(p).items() if k.endswith("_date")},
        reward_rates=rates,
        benefits=benefits,
        offers=offers,
        offer_absent_note=p.offer_absent_note,
        test_only=p.test_only,
    )


class Repository:
    def __init__(self, session: Session, *, allow_test_only: bool = False) -> None:
        self.s = session
        self.allow_test_only = allow_test_only
        self._banks: dict[str, str] | None = None

    def banks(self) -> dict[str, str]:
        if self._banks is None:
            q = select(P.Bank)
            if not self.allow_test_only:
                q = q.where(P.Bank.test_only.is_(False))
            self._banks = {b.bank_id: b.display_name for b in self.s.scalars(q)}
        return self._banks

    def _base(self) -> Select[Any]:
        q = (
            select(P.Product)
            .where(P.Product.status == "published")
            .options(
                selectinload(P.Product.card),
                selectinload(P.Product.checking),
                selectinload(P.Product.savings),
                selectinload(P.Product.reward_rates),
                selectinload(P.Product.benefits),
                selectinload(P.Product.offers),
            )
        )
        if not self.allow_test_only:
            q = q.where(P.Product.test_only.is_(False))
        return q

    def _apply(self, q: Select[Any], f: Filters) -> Select[Any]:
        if f.type:
            q = q.where(P.Product.product_type == f.type)
        if f.bank:
            q = q.where(P.Product.bank_id == f.bank)
        if f.q:
            like = f"%{f.q.lower()}%"
            q = q.where(
                or_(func.lower(P.Product.official_name).like(like), func.lower(P.Product.bank_id).like(like))
            )
        if f.verified_since:
            q = q.where(P.Product.last_confirmed_at >= f.verified_since)
        if f.annual_fee_max is not None:
            q = q.where(
                P.Product.id.in_(
                    select(P.CreditCardDetails.product_id).where(
                        P.CreditCardDetails.annual_fee_cents <= f.annual_fee_max * 100
                    )
                )
            )
        if f.segment:
            q = q.where(
                P.Product.id.in_(
                    select(P.CreditCardDetails.product_id).where(P.CreditCardDetails.segment == f.segment)
                )
            )
        for flag in f.card_flags or []:
            col = {
                "co_branded": P.CreditCardDetails.is_co_branded,
                "student": P.CreditCardDetails.is_student,
                "secured": P.CreditCardDetails.is_secured,
            }.get(flag)
            if col is not None:
                q = q.where(P.Product.id.in_(select(P.CreditCardDetails.product_id).where(col.is_(True))))
            elif flag == "business":
                q = q.where(
                    P.Product.id.in_(
                        select(P.CreditCardDetails.product_id).where(
                            P.CreditCardDetails.segment == "business"
                        )
                    )
                )
        if f.reward_category:
            q = q.where(
                P.Product.id.in_(
                    select(P.ProductRewardRate.product_id).where(
                        P.ProductRewardRate.category == f.reward_category
                    )
                )
            )
        if f.apy_min is not None:
            q = q.where(
                P.Product.id.in_(
                    select(P.SavingsAccountDetails.product_id).where(
                        P.SavingsAccountDetails.apy_pct >= f.apy_min
                    )
                )
            )
        if f.has_bonus:
            q = q.where(
                P.Product.id.in_(
                    select(P.Offer.product_id).where(
                        and_(P.Offer.status == "current", P.Offer.audience == "public")
                    )
                )
            )
        return q

    def list_products(
        self, f: Filters, now: datetime, page: int = 1, page_size: int = 20
    ) -> tuple[list[ProductView], int]:
        q = self._apply(self._base(), f).order_by(P.Product.bank_id, P.Product.official_name)
        views = [to_view(p, now, self.banks().get(p.bank_id, p.bank_id)) for p in self.s.scalars(q)]
        if f.has_bonus:  # request-time: expired/stale offers do not count as a bonus
            views = [v for v in views if any(o.state == "current" for o in v.offers)]
        return views[(page - 1) * page_size : page * page_size], len(views)

    def get(self, product_id: str, now: datetime) -> ProductView | None:
        import uuid

        try:
            pid = uuid.UUID(product_id)
        except ValueError:
            return None
        p = self.s.scalar(self._base().where(P.Product.id == pid))
        return to_view(p, now, self.banks().get(p.bank_id, p.bank_id)) if p else None

    def all_of_type(self, product_type: str, now: datetime) -> list[ProductView]:
        return self.list_products(Filters(type=product_type), now, page=1, page_size=10_000)[0]

    def history(self, product_id: str) -> list[dict[str, Any]]:
        import uuid

        try:
            pid = uuid.UUID(product_id)
        except ValueError:
            return []
        rows = self.s.scalars(
            select(P.ProductVersion)
            .where(P.ProductVersion.product_id == pid)
            .order_by(P.ProductVersion.version.desc())
        )
        out = [
            {
                "kind": "product",
                "version": v.version,
                "date": v.valid_from,
                "change_class": v.change_class,
                "changes": [c for c in v.change_summary if c.get("class") != "info"],
                "source_url": v.source_url,
            }
            for v in rows
        ]
        offer_rows = self.s.scalars(
            select(P.OfferVersion)
            .where(P.OfferVersion.product_id == pid)
            .order_by(P.OfferVersion.valid_from.desc())
        )
        for v in offer_rows:
            out.append(
                {
                    "kind": "offer",
                    "version": v.version,
                    "date": v.valid_from,
                    "change_class": v.change_class,
                    "changes": v.change_summary
                    or [{"field": "offer", "old": None, "new": "published", "class": v.change_class}],
                    "source_url": None,
                }
            )
        out.sort(key=lambda r: r["date"], reverse=True)  # type: ignore[arg-type,return-value]
        return out
