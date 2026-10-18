"""Extraction candidates produced by adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from bankrec.model import (
    BenefitRec,
    NullReason,
    OfferRec,
    PageType,
    ProductType,
    RewardRateRec,
    Sourced,
)

CARD_FIELDS = [
    "official_name",
    "product_family",
    "variant",
    "segment",
    "is_co_branded",
    "co_brand_partner",
    "is_student",
    "is_secured",
    "network",
    "annual_fee_cents",
    "intro_annual_fee_cents",
    "intro_annual_fee_months",
    "annual_fee_effective_date",
    "future_annual_fee_cents",
    "au_free_count",
    "au_fee_cents",
    "purchase_apr_min_pct",
    "purchase_apr_max_pct",
    "purchase_apr_variable",
    "intro_purchase_apr_pct",
    "intro_purchase_apr_months",
    "bt_apr_min_pct",
    "bt_apr_max_pct",
    "intro_bt_apr_pct",
    "intro_bt_apr_months",
    "intro_bt_window_days",
    "bt_fee_pct",
    "bt_fee_min_cents",
    "cash_apr_pct",
    "cash_fee_pct",
    "cash_fee_min_cents",
    "foreign_tx_fee_pct",
    "secured_min_deposit_cents",
    "secured_max_deposit_cents",
    "reward_currency",
    "reward_currency_name",
    "redemption_value_cents",
    "redemption_restriction",
    "reward_program",
    "base_rate",
    "credit_profile_guidance",
    "eligibility_restrictions",
    "terms_url",
]
CHECKING_FIELDS = [
    "official_name",
    "account_type",
    "monthly_fee_cents",
    "fee_waivers",
    "min_opening_deposit_cents",
    "overdraft_summary",
    "apy_tiers",
    "eligible_states",
    "customer_eligibility",
    "access_model",
    "terms_url",
]
SAVINGS_FIELDS = [
    "official_name",
    "apy_pct",
    "apy_tiers",
    "rate_type_note",
    "min_opening_deposit_cents",
    "min_balance_cents",
    "monthly_fee_cents",
    "fee_waivers",
    "withdrawal_restrictions",
    "max_withdrawals_per_month",
    "eligible_states",
    "customer_restrictions",
    "terms_url",
]
FIELDS_BY_TYPE = {
    ProductType.credit_card: CARD_FIELDS,
    ProductType.checking: CHECKING_FIELDS,
    ProductType.savings: SAVINGS_FIELDS,
}


class ProductCandidate(BaseModel):
    bank_id: str
    product_type: ProductType
    source_id: str
    url: str
    page_type: PageType
    parser_name: str
    parser_version: str
    retrieved_at: datetime
    capture_method: str = "automated"
    snapshot_id: str | None = None
    fields: dict[str, Sourced[Any]] = Field(default_factory=dict)
    reward_rates: list[Sourced[RewardRateRec]] = Field(default_factory=list)
    benefits: list[Sourced[BenefitRec]] = Field(default_factory=list)
    offers: list[Sourced[OfferRec]] = Field(default_factory=list)
    offer_absent_note: str | None = None
    # captured | none_stated (the issuer says there is none; evidence in fields["offer_capture"]) | unreadable (an
    # offer block was not read) | not_captured (script-only offers) | none_found (DESIGN §24.17 D)
    offer_status: str | None = None
    notes: list[str] = Field(default_factory=list)
    refused_fields: list[tuple[str, str]] = Field(default_factory=list)

    def value(self, name: str) -> Any:
        f = self.fields.get(name)
        return f.value if f is not None else None

    def set_missing_defaults(self) -> None:
        """Every declared field exists, either with a value or an explicit null reason."""
        for name in FIELDS_BY_TYPE[self.product_type]:
            self.fields.setdefault(name, Sourced(value=None, null_reason=NullReason.not_found))

    @property
    def name(self) -> str | None:
        v = self.value("official_name")
        return str(v) if v else None

    @property
    def missing_fields(self) -> list[str]:
        return sorted(
            k
            for k, v in self.fields.items()
            if v.value is None and v.null_reason is not NullReason.not_applicable
        )
