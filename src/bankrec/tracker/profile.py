"""What a visitor tells the offer check about themselves (DESIGN §27.10).

Every field is optional: the check works with whatever is given and says what is missing instead of assuming the
visitor qualifies. Nothing here identifies a person: no SSN, EIN, card number, account number or login is asked for.
The profile is sent only to compute one response and is never stored or logged (the web page keeps it in the
browser).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from bankrec.recommend.models import MonthlySpend

Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")]
BankId = Literal[
    "chase",
    "american_express",
    "citi",
    "capital_one",
    "bank_of_america",
    "discover",
    "wells_fargo",
    "other",
]
CardKey = Annotated[str, Field(max_length=80, pattern=r"^[a-z0-9_]+:[a-z0-9-]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeldCard(Strict):
    """A credit card the visitor has or had (their own account, or an authorized-user card on someone else's)."""

    card_key: CardKey | None = Field(None, description="a tracked card; empty for any other card")
    bank_id: BankId
    segment: Literal["personal", "business"] = "personal"
    authorized_user: bool = False
    opened: Month | None = Field(None, description="month the account was opened (or the card was added)")
    open_now: bool | None = Field(None, description="still open; empty = not said")
    bonus: Literal["yes", "no", "unknown"] = "unknown"
    bonus_month: Month | None = Field(None, description="month the welcome bonus was received")
    product_change: bool = Field(
        False, description="this card came from a product change (no new account was opened)"
    )
    original_bonus_month: Month | None = Field(
        None, description="with a product change: month a bonus was received on the original card"
    )
    no_annual_fee: bool | None = Field(None, description="for a card this site does not track")
    reports_to_personal: bool | None = Field(
        None, description="for a business card this site does not track: shows on personal credit reports"
    )


class MatchProfile(Strict):
    credit_score: Annotated[int, Field(ge=300, le=850)] | None = None
    score_model: Literal["fico", "vantage", "other", "unknown"] | None = None
    score_source: Annotated[str, Field(max_length=60)] | None = None
    credit_history: Literal["none", "lt_1y", "1_2y", "2_5y", "5y_plus"] | None = None
    negative_marks: bool | None = Field(
        None, description="late payments of 30+ days, collections or bankruptcy on the credit report"
    )
    student: bool | None = None
    cards: Annotated[list[HeldCard], Field(max_length=60)] = Field(default_factory=list)
    cards_complete: bool = Field(
        False,
        description="the list holds every credit card the visitor has had, open or closed, including"
        " authorized-user cards (so a card not listed was never held)",
    )
    new_accounts_24m: Annotated[int, Field(ge=0, le=60)] | None = Field(
        None,
        description="personal credit cards opened in the last 24 months with any bank, authorized-user cards"
        " included",
    )
    bank_relationships: Annotated[list[BankId], Field(max_length=8)] = Field(
        default_factory=list, description="banks where the visitor has a checking or savings account"
    )
    monthly_spend: Annotated[int, Field(ge=0, le=100_000)] | None = Field(
        None, description="normal monthly card spending in dollars, without any extra spending"
    )
    spend_categories: MonthlySpend | None = None
    max_annual_fee: Annotated[int, Field(ge=0, le=1000)] | None = None
    reward_preference: Literal["cashback", "points", "any"] | None = None
    business_income: Literal["yes", "no", "unsure"] | None = None
    annual_income: (
        Literal["none", "lt_25k", "25k_50k", "50k_100k", "100k_150k", "150k_plus", "prefer_not"] | None
    ) = Field(None, description="optional: yearly income you can access, as a range (never an exact figure)")
    as_of: date | None = Field(None, description="evaluate as of this date (tests); defaults to today")

    def natural_monthly_spend(self) -> int | None:
        if self.monthly_spend is not None:
            return self.monthly_spend
        if self.spend_categories is not None and self.spend_categories.total > 0:
            return self.spend_categories.total
        return None


class MatchRequest(Strict):
    profile: MatchProfile
    campaign_ids: Annotated[list[str], Field(max_length=100)] | None = Field(
        None, description="campaigns to check; empty = every current campaign"
    )
    point_values: dict[Annotated[str, Field(max_length=40)], Annotated[float, Field(ge=0, le=5)]] = Field(
        default_factory=dict, description="your own cents per point, per program"
    )
