from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bankrec.recommend import checking, savings
from bankrec.recommend.models import CheckingRequest, OfferView, ProductView, SavingsRequest

NOW = datetime(2026, 10, 12, tzinfo=UTC)


def acct(
    ptype: str,
    name: str = "Acct",
    offers: list[OfferView] | None = None,
    label: str = "verified",
    **details: Any,
) -> ProductView:
    return ProductView(
        id=name,
        bank_id="example_bank",
        bank_name="Example Bank",
        product_type=ptype,
        name=name,
        official_url="https://www.examplebank.example/x",
        label=label,
        verified_at=NOW,
        last_checked_at=NOW,
        first_published_at=NOW,
        details=details,
        offers=offers or [],
    )


def dd_offer(**kw: Any) -> OfferView:
    base = dict(
        id="o",
        offer_type="checking_bonus",
        reward_unit="cents",
        amount_qualifier="up_to",
        amount_min=None,
        amount_max=50000,
        requirement_type="direct_deposit_total",
        qualification_window_days=90,
        tiers=[
            {"amount": 30000, "requirement_min_cents": 200000},
            {"amount": 50000, "requirement_min_cents": 500000},
        ],
        offer_url="https://www.examplebank.example/x",
        verified_at=NOW,
        last_confirmed_at=NOW,
        state="current",
        verbatim_text="Earn up to $500",
    )
    base.update(kw)
    return OfferView(**base)


WAIVERS = [
    {"kind": "direct_deposit_total", "amount_cents": 50000, "text": "Direct deposits totaling $500"},
    {"kind": "min_daily_balance", "amount_cents": 150000, "text": "A minimum daily balance of $1,500"},
    {"kind": "age", "text": "Account owners under age 24"},
]


def creq(**kw: Any) -> CheckingRequest:
    return CheckingRequest(product_type="checking", **{"max_monthly_fee": 50, **kw})


def test_achievability_tiers_yes_and_no() -> None:
    p = acct("checking", offers=[dd_offer()], monthly_fee_cents=1200, fee_waivers=WAIVERS)
    hi = checking.recommend([p], creq(has_direct_deposit=True, monthly_direct_deposit=2000)).results[0]
    assert (
        hi.values.promotional_cents == 50000 and hi.achievability is not None and hi.achievability.achievable
    )
    assert hi.achievability.explanation == "Yes: $2,000/month × 3 months = $6,000 meets the $5,000 required."
    mid = checking.recommend([p], creq(has_direct_deposit=True, monthly_direct_deposit=1000)).results[0]
    assert mid.values.promotional_cents == 30000
    low = checking.recommend([p], creq(has_direct_deposit=True, monthly_direct_deposit=500)).results[0]
    assert low.values.promotional_cents == 0 and low.achievability is not None
    assert low.achievability.explanation.startswith("No: $500/month × 3 months = $1,500")
    none = checking.recommend([p], creq(has_direct_deposit=False)).results[0]
    assert none.values.promotional_cents == 0 and "don't have one" in (
        none.achievability.explanation if none.achievability else ""
    )


def test_deposit_count_requirement() -> None:
    p = acct("checking", offers=[dd_offer(required_dd_count=5)], monthly_fee_cents=0)
    r = checking.recommend([p], creq(has_direct_deposit=True, monthly_direct_deposit=5000)).results[0]
    assert r.values.promotional_cents == 0 and "5 deposits" in r.achievability.explanation  # type: ignore[union-attr]


def test_fee_waivers_and_net_value() -> None:
    p = acct("checking", monthly_fee_cents=1200, fee_waivers=WAIVERS)
    waived = checking.recommend([p], creq(has_direct_deposit=True, monthly_direct_deposit=600)).results[0]
    assert waived.values.first_year_cents == 0 and "waived for you" in waived.fee_text
    paid = checking.recommend([p], creq()).results[0]
    assert paid.values.first_year_cents == -14400
    assert any("Account owners under age 24" in x for x in paid.limitations)
    bal = checking.recommend([p], creq(can_maintain_balance=True, approx_balance=2000)).results[0]
    assert bal.values.first_year_cents == 0


def test_state_and_fee_filters() -> None:
    p = acct("checking", monthly_fee_cents=1200, eligible_states=["NY", "NJ"])
    assert checking.recommend([p], creq(state="CA")).excluded[0].reason == "not offered in CA"
    assert (
        checking.recommend([p], creq(state="NY", max_monthly_fee=5))
        .excluded[0]
        .reason.startswith("monthly fee")
    )
    assert checking.recommend([acct("checking", label="partially_verified")], creq()).results == []


def sreq(**kw: Any) -> SavingsRequest:
    return SavingsRequest(product_type="savings", **{"max_monthly_fee": 50, **kw})


TIERS = [
    {"min_balance_cents": 0, "max_balance_cents": 1000000, "apy_pct": "0.50"},
    {"min_balance_cents": 1000000, "max_balance_cents": 4999999, "apy_pct": "2.00"},
    {"min_balance_cents": 5000000, "max_balance_cents": None, "apy_pct": "3.25"},
]


def test_tier_apy_and_interest() -> None:
    p = acct("savings", apy_tiers=TIERS, monthly_fee_cents=0)
    r = savings.recommend([p], sreq(deposit_range="25k_100k", holding_months=12)).results[0]
    # midpoint 62,500 → 3.25% tier → $2,031.25 over 12 months
    assert r.values.first_year_cents == 203125
    assert any("variable" in a for a in r.assumptions)
    assert savings.tier_apy({"apy_tiers": TIERS}, 500000) == Decimal("0.50")


def savings_offer(**kw: Any) -> OfferView:
    base = dict(
        id="s",
        offer_type="savings_bonus",
        reward_unit="cents",
        amount_qualifier="exact",
        amount_min=20000,
        amount_max=20000,
        requirement_type="new_money_deposit",
        requirement_qualifier="exact",
        requirement_min_cents=1500000,
        requirement_max_cents=1500000,
        holding_period_days=90,
        offer_url="https://www.examplebank.example/x",
        verified_at=NOW,
        last_confirmed_at=NOW,
        state="current",
        verbatim_text="Earn a $200 bonus",
    )
    base.update(kw)
    return OfferView(**base)


def test_bonus_deposit_and_hold_rules() -> None:
    p = acct("savings", apy_pct=Decimal("4.00"), monthly_fee_cents=0, offers=[savings_offer()])
    ok = savings.recommend([p], sreq(deposit_range="25k_100k", holding_months=6)).results[0]
    assert (
        ok.values.promotional_cents == 20000 and ok.achievability is not None and ok.achievability.achievable
    )
    small = savings.recommend([p], sreq(deposit_range="1k_5k", holding_months=6)).results[0]
    assert small.values.promotional_cents == 0 and "below the $15,000" in small.achievability.explanation  # type: ignore[union-attr]
    short = savings.recommend([p], sreq(deposit_range="25k_100k", holding_months=2)).results[0]
    assert short.values.promotional_cents == 0 and "requires 90 days" in short.achievability.explanation  # type: ignore[union-attr]
    up = acct(
        "savings", apy_pct=Decimal("4.00"), offers=[savings_offer(amount_qualifier="up_to", amount_min=None)]
    )
    assert savings.recommend([up], sreq(deposit_range="25k_100k")).results[0].values.promotional_cents == 0


def test_liquidity_and_fee_waiver() -> None:
    limited = acct(
        "savings",
        name="Limited",
        apy_pct=Decimal("4.00"),
        max_withdrawals_per_month=6,
        withdrawal_restrictions="Limit of 6 withdrawals per statement cycle.",
    )
    free = acct("savings", name="Free", apy_pct=Decimal("4.00"))
    res = savings.recommend([limited, free], sreq(deposit_range="5k_25k", liquidity_need="high"))
    assert [r.product.name for r in res.results] == ["Free", "Limited"]
    fee = acct(
        "savings",
        name="Fee",
        apy_pct=Decimal("1.00"),
        monthly_fee_cents=500,
        fee_waivers=[
            {"kind": "min_daily_balance", "amount_cents": 30000, "text": "A minimum daily balance of $300"}
        ],
    )
    r = savings.recommend([fee], sreq(deposit_range="lt_1k")).results[0]
    assert "waived" in r.fee_text
    assert savings.recommend(
        [fee], sreq(deposit_range="lt_1k", max_monthly_fee=0)
    ).results  # waived → allowed


def test_intro_fee_waiver_and_bank_stated_eligibility_are_shown_not_inferred() -> None:
    periods = {
        "count": 2,
        "unit": "statement_period",
        "qualifier": "exact",
        "text": "waived for the first two statement periods",
    }
    months = {**periods, "unit": "month", "text": "waived for the first two months"}
    who = "We are currently accepting applications from Example Bank card members."
    a = acct(
        "checking", "Periods", monthly_fee_cents=1200, intro_fee_waiver=periods, customer_eligibility=who
    )
    b = acct("checking", "Months", monthly_fee_cents=1200, intro_fee_waiver=months)
    res = {r.product.name: r for r in checking.recommend([a, b], creq(), NOW).results}
    # statement periods are never converted to months: only a waiver stated in months lowers the estimate
    assert res["Periods"].values.first_year_cents == -1200 * 12
    assert res["Months"].values.first_year_cents == -1200 * 10
    assert "New accounts: monthly fee waived for the first 2 statement periods." in res["Periods"].limitations
    assert f"Who can open (as stated by the bank): {who}" in res["Periods"].limitations


def test_unstated_opening_deposit_never_excludes_and_a_stated_one_excludes_only_on_the_users_limit() -> None:
    stated = acct("checking", "Stated", monthly_fee_cents=0, min_opening_deposit_cents=10000)
    unstated = acct("checking", "Unstated", monthly_fee_cents=0)
    res = checking.recommend([stated, unstated], creq(), NOW)
    assert {r.product.name for r in res.results} == {"Stated", "Unstated"}
    note = "Minimum opening deposit: not stated — confirm with the bank."
    assert note in next(r for r in res.results if r.product.name == "Unstated").limitations
    limited = checking.recommend([stated, unstated], creq(max_opening_deposit=50), NOW)
    assert [r.product.name for r in limited.results] == ["Unstated"]
    assert [e.name for e in limited.excluded] == ["Stated"]
