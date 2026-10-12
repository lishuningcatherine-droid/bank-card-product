"""Published, user-facing tables (schema ``prod``). The API reads only these."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bankrec.db.base import ProdBase

Rate = Numeric(7, 4)
J = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Bank(ProdBase):
    __tablename__ = "banks"
    bank_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    official_domains: Mapped[list[str]] = mapped_column(ARRAY(Text))
    product_type_availability: Mapped[dict[str, Any]] = mapped_column(J)
    test_only: Mapped[bool] = mapped_column(Boolean, default=False)
    known_limitations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class RewardCategory(ProdBase):
    __tablename__ = "reward_categories"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(Text)


class Product(ProdBase):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("official_name <> '' AND lower(official_name) <> 'unknown'", name="name_not_unknown"),
        CheckConstraint("official_url LIKE 'https://%'", name="official_url_https"),
        CheckConstraint("product_type IN ('credit_card','checking','savings')", name="product_type"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    canonical_key: Mapped[str] = mapped_column(Text, unique=True)
    bank_id: Mapped[str] = mapped_column(ForeignKey("banks.bank_id"))
    product_type: Mapped[str] = mapped_column(String(20), index=True)
    official_name: Mapped[str] = mapped_column(Text)
    product_family: Mapped[str | None] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text)
    official_url: Mapped[str] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    apy_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="published")  # published | withdrawn
    missing_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    critical_missing: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    recheck_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    recheck_reason: Mapped[str | None] = mapped_column(Text)
    recheck_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    provider_only_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    offer_absent_note: Mapped[str | None] = mapped_column(Text)
    test_only: Mapped[bool] = mapped_column(Boolean, default=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    card: Mapped[CreditCardDetails | None] = relationship(back_populates="product", uselist=False,
                                                          cascade="all, delete-orphan")
    checking: Mapped[CheckingAccountDetails | None] = relationship(back_populates="product", uselist=False,
                                                                   cascade="all, delete-orphan")
    savings: Mapped[SavingsAccountDetails | None] = relationship(back_populates="product", uselist=False,
                                                                 cascade="all, delete-orphan")
    reward_rates: Mapped[list[ProductRewardRate]] = relationship(cascade="all, delete-orphan")
    benefits: Mapped[list[ProductBenefit]] = relationship(cascade="all, delete-orphan")
    offers: Mapped[list[Offer]] = relationship(back_populates="product", cascade="all, delete-orphan")
    aliases: Mapped[list[ProductAlias]] = relationship(cascade="all, delete-orphan")


class ProductAlias(ProdBase):
    __tablename__ = "product_aliases"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(Text)


class CreditCardDetails(ProdBase):
    __tablename__ = "credit_card_details"
    __table_args__ = (CheckConstraint("segment IN ('consumer','business')", name="segment"),)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    product: Mapped[Product] = relationship(back_populates="card")
    segment: Mapped[str] = mapped_column(String(10))
    is_co_branded: Mapped[bool] = mapped_column(Boolean, default=False)
    co_brand_partner: Mapped[str | None] = mapped_column(Text)
    is_student: Mapped[bool] = mapped_column(Boolean, default=False)
    is_secured: Mapped[bool] = mapped_column(Boolean, default=False)
    network: Mapped[str | None] = mapped_column(Text)
    annual_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    intro_annual_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    intro_annual_fee_months: Mapped[int | None] = mapped_column(Integer)
    annual_fee_effective_date: Mapped[date | None] = mapped_column(Date)
    future_annual_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    au_free_count: Mapped[int | None] = mapped_column(Integer)
    au_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    purchase_apr_min_pct: Mapped[Decimal | None] = mapped_column(Rate)
    purchase_apr_max_pct: Mapped[Decimal | None] = mapped_column(Rate)
    purchase_apr_variable: Mapped[bool | None] = mapped_column(Boolean)
    intro_purchase_apr_pct: Mapped[Decimal | None] = mapped_column(Rate)
    intro_purchase_apr_months: Mapped[int | None] = mapped_column(Integer)
    bt_apr_min_pct: Mapped[Decimal | None] = mapped_column(Rate)
    bt_apr_max_pct: Mapped[Decimal | None] = mapped_column(Rate)
    intro_bt_apr_pct: Mapped[Decimal | None] = mapped_column(Rate)
    intro_bt_apr_months: Mapped[int | None] = mapped_column(Integer)
    bt_fee_pct: Mapped[Decimal | None] = mapped_column(Rate)
    bt_fee_min_cents: Mapped[int | None] = mapped_column(BigInteger)
    cash_apr_pct: Mapped[Decimal | None] = mapped_column(Rate)
    cash_fee_pct: Mapped[Decimal | None] = mapped_column(Rate)
    cash_fee_min_cents: Mapped[int | None] = mapped_column(BigInteger)
    foreign_tx_fee_pct: Mapped[Decimal | None] = mapped_column(Rate)
    secured_min_deposit_cents: Mapped[int | None] = mapped_column(BigInteger)
    reward_currency: Mapped[str | None] = mapped_column(String(10))
    reward_program: Mapped[str | None] = mapped_column(Text)
    base_rate: Mapped[Decimal | None] = mapped_column(Rate)
    credit_profile_guidance: Mapped[str | None] = mapped_column(Text)
    eligibility_restrictions: Mapped[str | None] = mapped_column(Text)


class CheckingAccountDetails(ProdBase):
    __tablename__ = "checking_account_details"
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    product: Mapped[Product] = relationship(back_populates="checking")
    account_type: Mapped[str | None] = mapped_column(Text)
    monthly_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    fee_waivers: Mapped[list[dict[str, Any]] | None] = mapped_column(J)
    min_opening_deposit_cents: Mapped[int | None] = mapped_column(BigInteger)
    overdraft_summary: Mapped[str | None] = mapped_column(Text)
    apy_tiers: Mapped[list[dict[str, Any]] | None] = mapped_column(J)
    eligible_states: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    customer_eligibility: Mapped[str | None] = mapped_column(Text)
    access_model: Mapped[str | None] = mapped_column(String(10))


class SavingsAccountDetails(ProdBase):
    __tablename__ = "savings_account_details"
    __table_args__ = (CheckConstraint("apy_pct IS NULL OR (apy_pct >= 0 AND apy_pct <= 15)", name="apy_range"),)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    product: Mapped[Product] = relationship(back_populates="savings")
    apy_pct: Mapped[Decimal | None] = mapped_column(Rate)
    apy_tiers: Mapped[list[dict[str, Any]] | None] = mapped_column(J)
    rate_type_note: Mapped[str | None] = mapped_column(Text)
    min_opening_deposit_cents: Mapped[int | None] = mapped_column(BigInteger)
    min_balance_cents: Mapped[int | None] = mapped_column(BigInteger)
    monthly_fee_cents: Mapped[int | None] = mapped_column(BigInteger)
    fee_waivers: Mapped[list[dict[str, Any]] | None] = mapped_column(J)
    withdrawal_restrictions: Mapped[str | None] = mapped_column(Text)
    max_withdrawals_per_month: Mapped[int | None] = mapped_column(Integer)
    eligible_states: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    customer_restrictions: Mapped[str | None] = mapped_column(Text)


class ProductRewardRate(ProdBase):
    __tablename__ = "product_reward_rates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(ForeignKey("reward_categories.code"))
    rate: Mapped[Decimal] = mapped_column(Rate)
    rate_unit: Mapped[str] = mapped_column(String(4))
    cap_cents: Mapped[int | None] = mapped_column(BigInteger)
    cap_period: Mapped[str | None] = mapped_column(String(12))
    cap_combined: Mapped[bool] = mapped_column(Boolean, default=False)
    cap_group: Mapped[str | None] = mapped_column(Text)
    post_cap_rate: Mapped[Decimal | None] = mapped_column(Rate)
    is_rotating: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_activation: Mapped[bool] = mapped_column(Boolean, default=False)
    portal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    ends_on: Mapped[date | None] = mapped_column(Date)
    conditions_text: Mapped[str] = mapped_column(Text)


class ProductBenefit(ProdBase):
    __tablename__ = "product_benefits"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    benefit_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    monetizable: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    period: Mapped[str | None] = mapped_column(String(12))
    period_years: Mapped[int | None] = mapped_column(Integer)
    merchant_restriction: Mapped[str | None] = mapped_column(Text)
    enrollment_required: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions_text: Mapped[str] = mapped_column(Text)


class Offer(ProdBase):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            "(amount_qualifier = 'exact' AND amount_min IS NOT NULL AND amount_min = amount_max) OR "
            "(amount_qualifier = 'up_to' AND amount_min IS NULL AND amount_max IS NOT NULL) OR "
            "(amount_qualifier = 'starting_at' AND amount_min IS NOT NULL AND amount_max IS NULL)",
            name="amount_qualifier_shape",
        ),
        CheckConstraint(
            "requirement_qualifier IS NULL OR "
            "(requirement_qualifier = 'exact' AND requirement_min_cents = requirement_max_cents) OR "
            "(requirement_qualifier = 'up_to' AND requirement_min_cents IS NULL) OR "
            "(requirement_qualifier = 'starting_at' AND requirement_max_cents IS NULL)",
            name="requirement_qualifier_shape",
        ),
        CheckConstraint("audience IN ('public','targeted')", name="audience"),
        CheckConstraint("status IN ('current','expired','uncertain','targeted','recheck_pending')", name="status"),
        CheckConstraint("qualification_window_days IS NULL OR qualification_window_days > 0", name="window_pos"),
        UniqueConstraint("offer_key", name="offer_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    offer_key: Mapped[str] = mapped_column(Text)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    product: Mapped[Product] = relationship(back_populates="offers")
    offer_type: Mapped[str] = mapped_column(String(20))
    reward_unit: Mapped[str] = mapped_column(String(8))
    amount_qualifier: Mapped[str] = mapped_column(String(12))
    amount_min: Mapped[int | None] = mapped_column(BigInteger)
    amount_max: Mapped[int | None] = mapped_column(BigInteger)
    stated_cash_value_cents: Mapped[int | None] = mapped_column(BigInteger)
    requirement_type: Mapped[str | None] = mapped_column(String(30))
    requirement_qualifier: Mapped[str | None] = mapped_column(String(12))
    requirement_min_cents: Mapped[int | None] = mapped_column(BigInteger)
    requirement_max_cents: Mapped[int | None] = mapped_column(BigInteger)
    required_dd_count: Mapped[int | None] = mapped_column(Integer)
    qualification_window_days: Mapped[int | None] = mapped_column(Integer)
    qualification_window_months: Mapped[int | None] = mapped_column(Integer)
    qualification_window_text: Mapped[str | None] = mapped_column(Text)
    holding_period_days: Mapped[int | None] = mapped_column(Integer)
    open_by_date: Mapped[date | None] = mapped_column(Date)
    promo_code: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    audience: Mapped[str] = mapped_column(String(10))
    eligibility_restrictions: Mapped[str | None] = mapped_column(Text)
    offer_url: Mapped[str] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    verbatim_text: Mapped[str] = mapped_column(Text)
    qualifier_evidence: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    tiers: Mapped[list[dict[str, Any]]] = mapped_column(J, default=list)
    capture_conditions: Mapped[dict[str, Any] | None] = mapped_column(J)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="current")
    recheck_reason: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1)


class ProductVersion(ProdBase):
    __tablename__ = "product_versions"
    __table_args__ = (UniqueConstraint("product_id", "version", name="product_version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(J)
    change_summary: Mapped[list[dict[str, Any]]] = mapped_column(J, default=list)
    change_class: Mapped[str] = mapped_column(String(10))  # initial | minor | major
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class OfferVersion(ProdBase):
    __tablename__ = "offer_versions"
    __table_args__ = (UniqueConstraint("offer_id", "version", name="offer_version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(J)
    change_summary: Mapped[list[dict[str, Any]]] = mapped_column(J, default=list)
    change_class: Mapped[str] = mapped_column(String(10))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(Text)


class FieldProvenance(ProdBase):
    __tablename__ = "field_provenance"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"))
    field_path: Mapped[str] = mapped_column(Text)
    null_reason: Mapped[str | None] = mapped_column(String(20))
    snapshot_id: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    span_text: Mapped[str | None] = mapped_column(Text)
    parser_name: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    provenance_class: Mapped[str] = mapped_column(String(24))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
