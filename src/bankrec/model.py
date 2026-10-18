"""Pipeline domain model.

Every extracted field is a :class:`Sourced` value. The provenance guard lives in
:meth:`ExtractionContext.field`: a non-null value is accepted only if its quoted source text is found in the
stored snapshot text. Missing values carry an explicit :class:`NullReason`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class NullReason(StrEnum):
    not_found = "not_found"
    not_applicable = "not_applicable"
    ambiguous = "ambiguous"
    conflict = "conflict"
    requires_render = "requires_render"


class ProvenanceClass(StrEnum):
    official_page = "official_page"
    official_pdf = "official_pdf"
    manual_capture = "manual_capture"
    licensed_provider = "licensed_provider"
    regulator_dataset = "regulator_dataset"


class ProductType(StrEnum):
    credit_card = "credit_card"
    checking = "checking"
    savings = "savings"


class SourceKind(StrEnum):
    product_detail = "product_detail"
    offer_detail = "offer_detail"
    comparison = "comparison"
    listing = "listing"
    terms_pdf = "terms_pdf"
    terms_page = "terms_page"  # HTML pricing/terms page linked from a product page (DESIGN §24.12)
    manual_snapshot = "manual_snapshot"
    regulator_dataset = "regulator_dataset"
    licensed_data_provider = "licensed_data_provider"


class PageType(StrEnum):
    official_product_detail = "official_product_detail"
    official_offer_detail = "official_offer_detail"
    official_comparison_page = "official_comparison_page"
    official_marketing_page = "official_marketing_page"
    terms_page = "terms_page"
    pdf_terms = "pdf_terms"
    article = "article"
    faq = "faq"
    category_page = "category_page"
    login_page = "login_page"
    blocked_page = "blocked_page"
    empty_page = "empty_page"
    invalid_page = "invalid_page"
    unknown_page = "unknown_page"


EXTRACTABLE_PAGE_TYPES = {
    PageType.official_product_detail,
    PageType.official_offer_detail,
    PageType.official_comparison_page,
    PageType.terms_page,
    PageType.pdf_terms,
}

#: Source priority (higher wins). Regulator data never publishes.
PRIORITY = {
    PageType.official_product_detail: 100,
    PageType.official_offer_detail: 90,
    PageType.pdf_terms: 80,
    PageType.terms_page: 80,
    PageType.official_comparison_page: 50,
}
PROVIDER_PRIORITY = 30


class Sourced(BaseModel, Generic[T]):
    """A field value plus its evidence."""

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    null_reason: NullReason | None = None
    span_text: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    confidence: float = 0.0
    provenance_class: ProvenanceClass = ProvenanceClass.official_page
    method: str = "label_regex"

    @model_validator(mode="after")
    def _check(self) -> Sourced[T]:
        if self.value is None and self.null_reason is None:
            raise ValueError("missing value requires a null_reason")
        if self.value is not None and not self.span_text:
            raise ValueError("value without source text span is refused")
        return self

    @property
    def present(self) -> bool:
        return self.value is not None


def missing(reason: NullReason = NullReason.not_found) -> Sourced[Any]:
    return Sourced(value=None, null_reason=reason)


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class ProvenanceError(ValueError):
    pass


METHOD_CONFIDENCE = {
    "table_cell": 1.0,
    "label_regex": 0.9,
    "free_text": 0.75,
    "manual_review": 1.0,
    "provider": 0.8,
}


class ExtractionContext:
    """Holds the snapshot text an adapter extracts from and enforces the provenance guard."""

    def __init__(
        self,
        text: str,
        source_confidence: float = 1.0,
        provenance_class: ProvenanceClass = ProvenanceClass.official_page,
    ) -> None:
        self.text = text
        self._norm = norm_ws(text).lower()
        self.source_confidence = source_confidence
        self.provenance_class = provenance_class
        self.refused: list[tuple[str, str]] = []

    def locate(self, span_text: str) -> tuple[int, int] | None:
        needle = norm_ws(span_text).lower()
        if not needle:
            return None
        i = self._norm.find(needle)
        return (i, i + len(needle)) if i >= 0 else None

    def field(
        self,
        value: T | None,
        span_text: str | None,
        *,
        method: str = "label_regex",
        null_reason: NullReason = NullReason.not_found,
        name: str = "",
    ) -> Sourced[T]:
        if value is None:
            return Sourced(value=None, null_reason=null_reason)
        if not span_text:
            self.refused.append((name, "no span"))
            return Sourced(value=None, null_reason=NullReason.not_found)
        loc = self.locate(span_text)
        if loc is None:
            self.refused.append((name, span_text[:80]))
            return Sourced(value=None, null_reason=NullReason.not_found)
        return Sourced(
            value=value,
            span_text=norm_ws(span_text),
            span_start=loc[0],
            span_end=loc[1],
            confidence=round(METHOD_CONFIDENCE.get(method, 0.75) * self.source_confidence, 4),
            provenance_class=self.provenance_class,
            method=method,
        )


# ---------------------------------------------------------------- structured sub-values


class FeeWaiver(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "min_daily_balance",
        "min_avg_balance",
        "direct_deposit_total",
        "electronic_deposit_total",
        "linked_account",
        "age",
        "student",
        "other",
    ]
    amount_cents: int | None = None
    age_max: int | None = None
    age_min: int | None = None
    period: str | None = None
    text: str


class ApyTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    min_balance_cents: int
    max_balance_cents: int | None
    apy_pct: Decimal


ConditionKind = Literal[
    "portal_only",  # only when booked through the issuer's travel portal
    "booked_direct",  # only when booked directly with the airline / hotel
    "partner_only",  # only at the co-brand partner (detail = partner)
    "us_only",  # U.S. merchants only
    "excludes_superstores",  # superstores (e.g. Target, Walmart) are not in the category
    "excludes_warehouse_clubs",  # warehouse clubs are not in the category
    "enrollment_required",  # enrollment / activation required
]


class RateCondition(BaseModel):
    """A qualifier that limits where a rate applies, with the page text that states it (spot-check round 2, A)."""

    model_config = ConfigDict(frozen=True)
    kind: ConditionKind
    text: str
    detail: str | None = None


class RewardRateRec(BaseModel):
    model_config = ConfigDict(frozen=True)
    category: str
    rate: Decimal
    rate_unit: Literal["pct", "x"]
    cap_cents: int | None = None
    cap_period: str | None = None
    cap_combined: bool = False
    cap_group: str | None = None
    post_cap_rate: Decimal | None = None
    is_rotating: bool = False
    requires_activation: bool = False
    portal_only: bool = False
    ends_on: date | None = None
    text: str
    conditions: list[RateCondition] = Field(default_factory=list)


class BenefitRec(BaseModel):
    model_config = ConfigDict(frozen=True)
    benefit_type: str  # travel | hotel | airline | dining | grocery | gas | entertainment | transit | statement_credit | other
    name: str
    monetizable: bool = False
    amount_cents: int | None = None
    period: str | None = None  # monthly | semiannual | annual | multi_year
    period_years: int | None = None
    merchant_restriction: str | None = None
    enrollment_required: bool = False
    # what earns the credit, in the page's words ("for 11 consecutive months of purchases")
    condition: str | None = None
    text: str

    @property
    def annual_value_cents(self) -> int | None:
        if not self.monetizable or self.amount_cents is None or self.period is None:
            return None
        mult = {"monthly": 12, "quarterly": 4, "semiannual": 2, "annual": 1}.get(self.period)
        if mult is not None:
            return self.amount_cents * mult
        if self.period == "multi_year" and self.period_years:
            return self.amount_cents // self.period_years
        return None


class OfferTier(BaseModel):
    model_config = ConfigDict(frozen=True)
    amount: int
    requirement_min_cents: int | None
    requirement_max_cents: int | None = None
    text: str
    # Tiered welcome offers (spot-check round 1, finding 10): each tier's own spend and window. ``incremental``: the
    # requirement is "another/additional $X" on top of the previous tiers' spend. requirement None = non-spend tier
    # (e.g. "add an authorized user"), never counted in value.
    window_days: int | None = None  # set only when the page states days
    incremental: bool = False
    # The tier's window as stated: count + unit (days | weeks | months | years | billing_cycles), never converted.
    window_count: int | None = None
    window_unit: str | None = None


class OfferRec(BaseModel):
    offer_type: Literal["card_welcome", "checking_bonus", "savings_bonus", "intro_apr", "annual_fee_waiver"]
    reward_unit: Literal["cents", "points", "miles"]
    amount_qualifier: Literal["exact", "up_to", "starting_at", "tiered"]
    amount_min: int | None
    amount_max: int | None
    stated_cash_value_cents: int | None = None
    requirement_type: str | None = None
    requirement_qualifier: Literal["exact", "up_to", "starting_at"] | None = None
    requirement_min_cents: int | None = None
    requirement_max_cents: int | None = None
    required_dd_count: int | None = None
    # Windows keep the unit the page states (spot-check round 2, finding C): count + unit, and the days / months
    # columns only when the page says days / months. "3 months" is never stored as 90 days.
    qualification_window_days: int | None = None
    qualification_window_months: int | None = None
    qualification_window_count: int | None = None
    qualification_window_unit: str | None = None
    qualification_window_text: str | None = None
    holding_period_days: int | None = None
    holding_period_count: int | None = None
    holding_period_unit: str | None = None
    open_by_date: date | None = None
    promo_code: str | None = None
    start_date: date | None = None
    expiration_date: date | None = None
    audience: Literal["public", "targeted"] = "public"
    eligibility_restrictions: str | None = None
    offer_url: str
    terms_url: str | None = None
    verbatim_text: str
    qualifier_evidence: str | None = None
    note: str | None = None
    tiers: list[OfferTier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _qualifier_shape(self) -> OfferRec:
        q, lo, hi = self.amount_qualifier, self.amount_min, self.amount_max
        if q == "exact" and not (lo is not None and lo == hi):
            raise ValueError("exact offers need amount_min == amount_max")
        if q == "up_to" and not (lo is None and hi is not None):
            raise ValueError("up_to offers need amount_min NULL and amount_max set")
        if q == "starting_at" and not (lo is not None and hi is None):
            raise ValueError("starting_at offers need amount_min set and amount_max NULL")
        if q == "tiered" and not (len(self.tiers) >= 2 and hi == sum(t.amount for t in self.tiers)):
            raise ValueError("tiered offers need >= 2 tiers and amount_max == the sum of tier amounts")
        return self


def utcnow() -> datetime:
    return datetime.now(UTC)
