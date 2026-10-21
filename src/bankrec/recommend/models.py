"""Recommendation request/response models (also the API schemas). Inputs are broad ranges only."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

Dollars = Annotated[int, Field(ge=0, le=50_000)]
Importance = Literal["low", "medium", "high"]
STATES = Literal[
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MonthlySpend(Strict):
    groceries: Dollars = 0
    dining: Dollars = 0
    travel: Dollars = 0
    gas: Dollars = 0
    entertainment: Dollars = 0
    transit: Dollars = 0
    online_shopping: Dollars = 0
    other: Dollars = 0

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class CardRequest(Strict):
    product_type: Literal["credit_card"]
    goal: Literal["cashback", "travel", "welcome_bonus", "low_interest", "balance_transfer", "build_credit"]
    monthly_spend: MonthlySpend = Field(default_factory=MonthlySpend)
    travel_frequency: Literal["none", "occasional", "frequent"] = "none"
    preferred_reward: Literal["cashback", "points", "miles", "any"] = "any"
    max_annual_fee: Annotated[int, Field(ge=0, le=1000)] = 0
    exclude_over_max_fee: bool = True
    avoid_foreign_fee: bool = False
    credit_profile: Literal["excellent", "good", "fair", "limited", "unknown"] = "unknown"
    segment: Literal["consumer", "business", "either"] = "consumer"
    include_co_branded: bool = True
    preferred_partner: Annotated[str, Field(max_length=40)] | None = None
    card_kind: Literal["any", "student", "secured"] = "any"
    bonus_importance: Importance = "medium"
    selected_credit_ids: Annotated[list[str], Field(max_length=50)] = Field(default_factory=list)
    opt_in_rotating: bool = False
    # Rates limited to the issuer's travel portal / to booking directly with the airline or hotel count only when
    # the user says they book that way (DESIGN §24.17 A).
    opt_in_portal: bool = False
    opt_in_booked_direct: bool = False
    cents_per_point: Annotated[Decimal, Field(ge=0, le=5)] | None = None


class CheckingRequest(Strict):
    product_type: Literal["checking"]
    has_direct_deposit: bool = False
    monthly_direct_deposit: Annotated[int, Field(ge=0, le=100_000)] = 0
    can_maintain_balance: bool = False
    approx_balance: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    max_monthly_fee: Annotated[int, Field(ge=0, le=50)] = 0
    state: STATES | None = None
    access_preference: Literal["branch", "online", "either"] = "either"
    bonus_importance: Importance = "medium"
    # the most the user can deposit to open the account, when they say so; only a stated minimum above it excludes
    max_opening_deposit: Annotated[int, Field(ge=0, le=1_000_000)] | None = None


class SavingsRequest(Strict):
    product_type: Literal["savings"]
    deposit_range: Literal["lt_1k", "1k_5k", "5k_25k", "25k_100k", "100k_plus"]
    holding_months: Annotated[int, Field(ge=1, le=60)] = 12
    liquidity_need: Literal["low", "medium", "high"] = "medium"
    max_monthly_fee: Annotated[int, Field(ge=0, le=50)] = 0
    state: STATES | None = None
    apy_vs_bonus: Literal["apy", "balanced", "bonus"] = "balanced"


RecommendRequest = Annotated[
    CardRequest | CheckingRequest | SavingsRequest, Field(discriminator="product_type")
]


# ------------------------------------------------------------------------------------------------ product DTOs
class SeenOn(BaseModel):
    """One official page (channel) that showed the offer."""

    url: str
    channel: str | None = None  # product_page | offer_page | comparison_page | terms_page | manual_capture
    last_confirmed_at: datetime | None = None


class OfferView(BaseModel):
    id: str
    offer_type: str
    reward_unit: str
    amount_qualifier: Literal["exact", "up_to", "starting_at", "tiered"]
    amount_min: int | None
    amount_max: int | None
    requirement_type: str | None = None
    requirement_qualifier: str | None = None
    requirement_min_cents: int | None = None
    requirement_max_cents: int | None = None
    required_dd_count: int | None = None
    qualification_window_days: int | None = None
    qualification_window_months: int | None = None
    qualification_window_count: int | None = None
    qualification_window_unit: str | None = None
    holding_period_days: int | None = None
    holding_period_count: int | None = None
    holding_period_unit: str | None = None
    expiration_date: date | None = None
    tiers: list[dict[str, Any]] = Field(default_factory=list)
    offer_url: str
    verified_at: datetime
    last_confirmed_at: datetime
    state: str  # current | expired | stale | uncertain | recheck_pending (request-time)
    verbatim_text: str
    note: str | None = None
    eligibility_restrictions: str | None = None
    open_by_date: date | None = None
    # public | targeted | referral | preapproved: only public offers are ranked or recommended (DESIGN §25.1)
    audience: Literal["public", "targeted", "referral", "preapproved"] = "public"
    seen_on: list[SeenOn] = Field(default_factory=list)


class RateConditionView(BaseModel):
    kind: str  # portal_only | booked_direct | partner_only | us_only | excludes_superstores | excludes_warehouse_clubs | enrollment_required
    text: str
    detail: str | None = None


class RateView(BaseModel):
    category: str
    rate: Decimal
    rate_unit: str
    cap_cents: int | None = None
    cap_period: str | None = None
    cap_combined: bool = False
    cap_group: str | None = None
    post_cap_rate: Decimal | None = None
    is_rotating: bool = False
    requires_activation: bool = False
    portal_only: bool = False
    ends_on: date | None = None
    text: str = ""
    conditions: list[RateConditionView] = Field(default_factory=list)


class BenefitView(BaseModel):
    id: str
    benefit_type: str
    name: str
    monetizable: bool
    amount_cents: int | None = None
    period: str | None = None
    period_years: int | None = None
    annual_value_cents: int | None = None
    enrollment_required: bool = False
    merchant_restriction: str | None = None
    condition: str | None = None


class ProductView(BaseModel):
    id: str
    bank_id: str
    bank_name: str
    product_type: Literal["credit_card", "checking", "savings"]
    name: str
    official_url: str
    terms_url: str | None = None
    label: Literal["verified", "partially_verified"]
    label_reasons: list[str] = Field(default_factory=list)
    verified_at: datetime
    last_checked_at: datetime
    last_changed_at: datetime | None = None
    first_published_at: datetime
    recheck_pending: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    provider_only_fields: list[str] = Field(default_factory=list)
    details: dict[str, Any]
    reward_rates: list[RateView] = Field(default_factory=list)
    benefits: list[BenefitView] = Field(default_factory=list)
    offers: list[OfferView] = Field(default_factory=list)
    offer_absent_note: str | None = None
    offer_status: str | None = None
    test_only: bool = False


# ------------------------------------------------------------------------------------------------ results
class Component(BaseModel):
    key: str
    label: str
    weight: float
    normalized: float
    contribution: float  # points out of 100


class Reason(BaseModel):
    code: str
    text: str
    params: dict[str, Any] = Field(default_factory=dict)


class Values(BaseModel):
    ongoing_annual_cents: int
    promotional_cents: int
    first_year_cents: int
    year1_cents: int | None = None
    year2_cents: int | None = None
    year3_cents: int | None = None
    three_year_total_cents: int | None = None
    non_monetized: list[str] = Field(default_factory=list)
    credits_counted: list[dict[str, Any]] = Field(default_factory=list)


class Achievability(BaseModel):
    achievable: bool
    explanation: str


class Result(BaseModel):
    rank: int
    product: ProductView
    # Internal only (owner decision 2026-10-19): the deterministic baseline score and its components order the
    # results and feed the ranking layer, but are never serialized to the API or shown (DESIGN §26.6).
    score: SkipJsonSchema[float] = Field(exclude=True)
    components: SkipJsonSchema[list[Component]] = Field(exclude=True)
    values: Values
    fee_text: str
    current_offer: OfferView | None = None
    possible_welcome_offer: str | None = None
    offer_note: str | None = None
    achievability: Achievability | None = None
    break_even: str | None = None
    over_budget_note: str | None = None
    top_features: list[str] = Field(default_factory=list)
    why: list[Reason] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class Excluded(BaseModel):
    product_id: str
    name: str
    reason: str


class RecommendResponse(BaseModel):
    product_type: str
    generated_at: datetime
    # which ranking ordered the results: "baseline" (deterministic) or a ranking-model id (DESIGN §26.8)
    ranker: str = "baseline"
    results: list[Result]
    excluded: list[Excluded] = Field(default_factory=list)
    disclaimer: str
