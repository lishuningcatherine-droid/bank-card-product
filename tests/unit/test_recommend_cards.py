"""Credit-card formulas, checked against hand-computed values (fictional products)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from bankrec.recommend import cards
from bankrec.recommend.models import BenefitView, CardRequest, MonthlySpend, OfferView, ProductView, RateView

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def rate(cat: str, r: str, unit: str = "pct", **kw: Any) -> RateView:
    return RateView(category=cat, rate=Decimal(r), rate_unit=unit, **kw)


def offer(**kw: Any) -> OfferView:
    base = dict(
        id="o1",
        offer_type="card_welcome",
        reward_unit="cents",
        amount_qualifier="exact",
        amount_min=20000,
        amount_max=20000,
        requirement_type="spend",
        requirement_qualifier="exact",
        requirement_min_cents=400000,
        requirement_max_cents=400000,
        qualification_window_months=3,
        offer_url="https://www.examplebank.example/x",
        verified_at=NOW,
        last_confirmed_at=NOW,
        state="current",
        verbatim_text="Earn a $200 bonus after you spend $4,000 in the first 3 months.",
    )
    base.update(kw)
    return OfferView(**base)


def card(
    name: str = "Card A",
    rates: list[RateView] | None = None,
    offers: list[OfferView] | None = None,
    benefits: list[BenefitView] | None = None,
    label: str = "verified",
    **details: Any,
) -> ProductView:
    d = dict(
        segment="consumer",
        annual_fee_cents=0,
        reward_currency="cashback",
        base_rate=Decimal("1"),
        foreign_tx_fee_pct=Decimal("3"),
        purchase_apr_min_pct=Decimal("19.24"),
        is_secured=False,
        is_student=False,
        is_co_branded=False,
    )
    d.update(details)
    return ProductView(
        id=name,
        bank_id="example_bank",
        bank_name="Example Bank",
        product_type="credit_card",
        name=name,
        official_url="https://www.examplebank.example/x",
        label=label,
        verified_at=NOW,
        last_checked_at=NOW,
        first_published_at=NOW,
        details=d,
        reward_rates=rates if rates is not None else [rate("other", "1")],
        offers=offers or [],
        benefits=benefits or [],
    )


def req(**kw: Any) -> CardRequest:
    base: dict[str, Any] = dict(
        product_type="credit_card", goal="cashback", max_annual_fee=1000, exclude_over_max_fee=False
    )
    base.update(kw)
    return CardRequest(**base)


def spend(**kw: int) -> MonthlySpend:
    return MonthlySpend(**kw)


GROCERY_CAP = "2% cash back at grocery stores on up to $2,000 in combined purchases each quarter, then 1%"


def test_caps_overflow_and_base() -> None:
    p = card(
        rates=[
            rate(
                "groceries",
                "2",
                cap_cents=200000,
                cap_period="quarterly",
                cap_combined=True,
                cap_group=GROCERY_CAP,
                post_cap_rate=Decimal("1"),
            ),
            rate("dining", "3"),
            rate("other", "1"),
        ]
    )
    r = req(monthly_spend=spend(groceries=1000, dining=200, other=500))
    cents, per_cat, share, _ = cards.annual_rewards(p, r, Decimal(1), NOW)
    # groceries: 8,000 in cap × 2% = $160 + 4,000 × 1% = $40; dining 2,400 × 3% = $72; other 6,000 × 1% = $60
    assert per_cat["groceries"] == 20000 and per_cat["dining"] == 7200 and per_cat["everything_else"] == 6000
    assert cents == 33200
    assert share == pytest.approx(10400 / 20400)


def test_combined_cap_shared_across_categories() -> None:
    group = "on up to $1,000 in combined purchases each month"
    p = card(
        rates=[
            rate(
                "groceries", "3", cap_cents=100000, cap_period="monthly", cap_combined=True, cap_group=group
            ),
            rate("gas", "3", cap_cents=100000, cap_period="monthly", cap_combined=True, cap_group=group),
        ]
    )
    r = req(monthly_spend=spend(groceries=800, gas=800))
    cents, per_cat, _, _ = cards.annual_rewards(p, r, Decimal(1), NOW)
    # one $12,000/yr cap shared: groceries 9,600 × 3% = 288; gas 2,400 × 3% + 7,200 × 1% = 72 + 72
    assert per_cat["groceries"] == 28800 and per_cat["gas"] == 14400 and cents == 43200


def test_points_valuation_portal_excluded_and_override() -> None:
    p = card(
        reward_currency="points",
        rates=[rate("travel", "5", "x", portal_only=True), rate("travel", "3", "x"), rate("other", "1", "x")],
    )
    r = req(monthly_spend=spend(travel=500))
    assert cards.annual_rewards(p, r, Decimal(1), NOW)[0] == 18000  # 6,000 × 3 pts × 1.0¢
    assert cards.annual_rewards(p, r, Decimal("1.5"), NOW)[0] == 27000
    c = cards.calc(p, req(monthly_spend=spend(travel=500), cents_per_point=Decimal("1.5")), NOW)
    assert c.rewards_cents == 27000 and c.cpp_basis == "your adjustment"
    assert any("Portal-only" in n for n in c.limitations)


def test_rotating_base_unless_opt_in() -> None:
    p = card(
        rates=[
            rate(
                "rotating",
                "5",
                cap_cents=150000,
                cap_period="quarterly",
                is_rotating=True,
                requires_activation=True,
            ),
            rate("other", "1"),
        ]
    )
    assert cards.annual_rewards(p, req(monthly_spend=spend(other=1000)), Decimal(1), NOW)[0] == 12000
    # opt in: 25% of 12,000 = 3,000 (≤ $6,000 cap) × 5% = 150 + 9,000 × 1% = 90
    assert (
        cards.annual_rewards(p, req(monthly_spend=spend(other=1000), opt_in_rotating=True), Decimal(1), NOW)[
            0
        ]
        == 24000
    )


def test_time_bound_rate_counted_until_end() -> None:
    p = card(rates=[rate("gas", "4", ends_on=date(2027, 4, 11)), rate("other", "1")])
    cents, per_cat, _, notes = cards.annual_rewards(p, req(monthly_spend=spend(gas=100)), Decimal(1), NOW)
    # 6 of 12 months at 4%: 600 × 4% = 24; remaining 600 at 1% = 6
    assert per_cat["gas"] == 2400 and cents == 3000 and any("ends" in n for n in notes)


def test_unchecked_credits_not_counted() -> None:
    credit = BenefitView(
        id="b1",
        benefit_type="travel",
        name="$50 annual travel credit",
        monetizable=True,
        amount_cents=5000,
        period="annual",
        annual_value_cents=5000,
    )
    p = card(benefits=[credit])
    assert cards.calc(p, req(), NOW).credits_cents == 0
    c = cards.calc(p, req(selected_credit_ids=["b1"]), NOW)
    assert c.credits_cents == 5000 and c.credits_counted[0]["name"] == "$50 annual travel credit"


def test_bonus_only_when_achievable_and_exact() -> None:
    p = card(offers=[offer()])
    ok = cards.calc(p, req(monthly_spend=spend(other=1500)), NOW)
    assert ok.promo_cents == 20000 and ok.achievability is not None and ok.achievability.achievable
    assert ok.first_year == ok.ongoing + 20000
    no = cards.calc(p, req(monthly_spend=spend(other=1000)), NOW)
    assert no.promo_cents == 0 and no.achievability is not None and not no.achievability.achievable
    assert "$3,000" in no.achievability.explanation and "$4,000" in no.achievability.explanation


@pytest.mark.parametrize("q", ["up_to", "starting_at"])
def test_up_to_and_starting_at_contribute_zero(q: str) -> None:
    o = offer(
        amount_qualifier=q,
        amount_min=None if q == "up_to" else 20000,
        amount_max=80000 if q == "up_to" else None,
        reward_unit="points",
        verbatim_text="Earn up to 80,000 points" if q == "up_to" else "Earn at least 20,000 points",
    )
    p = card(offers=[o], reward_currency="points", rates=[rate("other", "1", "x")])
    res = cards.recommend([p], req(monthly_spend=spend(other=5000), bonus_importance="high"), NOW)
    r = res.results[0]
    assert r.values.promotional_cents == 0 and r.values.first_year_cents == r.values.ongoing_annual_cents
    assert r.possible_welcome_offer is not None
    if q == "up_to":
        assert r.possible_welcome_offer == (
            "Possible welcome offer: up to 80,000 points (your offer is shown during "
            "application and may be lower)."
        )
        assert any(c.key == "possible_offer_signal" for c in r.components)


def test_signal_only_at_high_importance() -> None:
    o = offer(amount_qualifier="up_to", amount_min=None, amount_max=80000, reward_unit="points")
    p = card(offers=[o])
    low = cards.recommend([p], req(bonus_importance="medium"), NOW).results[0]
    assert all(c.key != "possible_offer_signal" for c in low.components)


def test_first_year_fee_waiver_and_scheduled_change() -> None:
    p = card(
        annual_fee_cents=9500,
        intro_annual_fee_cents=0,
        intro_annual_fee_months=12,
        annual_fee_effective_date=date(2027, 3, 1),
        future_annual_fee_cents=12500,
    )
    r = cards.recommend([p], req(monthly_spend=spend(other=2000)), NOW).results[0]
    rewards = 24000
    assert r.values.ongoing_annual_cents == rewards - 9500
    assert r.values.first_year_cents == rewards  # $0 first year
    assert r.values.year2_cents == rewards - 12500 and r.values.year3_cents == rewards - 12500
    assert r.values.three_year_total_cents == rewards + 2 * (rewards - 12500)
    assert "$0 the first year" in r.fee_text and "$125" in r.fee_text


def test_fee_exclusion_and_over_budget_note() -> None:
    p = card(annual_fee_cents=9500)
    excl = cards.recommend([p], req(max_annual_fee=0, exclude_over_max_fee=True), NOW)
    assert not excl.results and "above your maximum" in excl.excluded[0].reason
    shown = cards.recommend(
        [p], req(max_annual_fee=0, exclude_over_max_fee=False, monthly_spend=spend(other=2000)), NOW
    ).results[0]
    assert shown.over_budget_note == (
        "Annual fee is above your maximum; estimated value exceeds the fee by $145 under your inputs."
    )
    lowval = cards.recommend(
        [p], req(max_annual_fee=0, exclude_over_max_fee=False, monthly_spend=spend(other=100)), NOW
    )
    assert not lowval.results


def test_apr_required_only_for_low_interest_goals() -> None:
    p = card(purchase_apr_min_pct=None)
    assert (
        cards.recommend([p], req(goal="low_interest"), NOW).excluded[0].reason.startswith("no verified APR")
    )
    r = cards.recommend([p], req(goal="cashback"), NOW).results[0]
    assert "APR: see issuer." in r.limitations


def test_offer_independent_verification_and_offer_states() -> None:
    plain = card(name="No offer")
    stale = card(name="Stale offer", offers=[offer(state="stale")])
    expired = card(name="Expired offer", offers=[offer(state="expired")])
    pending = card(name="Recheck", offers=[offer(state="recheck_pending")])
    res = cards.recommend([plain, stale, expired, pending], req(monthly_spend=spend(other=2000)), NOW)
    assert {r.product.name for r in res.results} == {"No offer", "Stale offer", "Expired offer", "Recheck"}
    assert all(r.values.promotional_cents == 0 and r.current_offer is None for r in res.results)


def test_hard_filters() -> None:
    biz = card(name="Biz", segment="business")
    sec = card(name="Secured", is_secured=True)
    stu = card(name="Student", is_student=True)
    co = card(name="Co", is_co_branded=True)
    part = card(name="Partial", label="partially_verified")
    guided = card(name="Guided", credit_profile_guidance="Good to Excellent")
    res = cards.recommend(
        [biz, sec, stu, co, part, guided], req(include_co_branded=False, credit_profile="fair"), NOW
    )
    assert res.results == []
    reasons = {e.name: e.reason for e in res.excluded}
    assert reasons["Partial"] == "not Verified" and "credit guidance" in reasons["Guided"]
    assert [r.product.name for r in cards.recommend([sec, stu], req(card_kind="secured"), NOW).results] == [
        "Secured"
    ]
    assert [r.product.name for r in cards.recommend([biz, sec], req(segment="business"), NOW).results] == [
        "Biz"
    ]


def test_break_even_and_explanations() -> None:
    p = card(annual_fee_cents=9500, rates=[rate("dining", "4"), rate("other", "1")])
    r = cards.recommend([p], req(monthly_spend=spend(dining=300)), NOW).results[0]
    assert r.break_even == "This card's fee is covered if you spend at least $197.91/month in dining."
    assert r.why and all(w.text for w in r.why)
    assert sum(c.contribution for c in r.components) == pytest.approx(r.score, abs=0.05)
    assert r.product.official_url.startswith("https://")


def test_ranking_is_deterministic() -> None:
    a = card(name="A", rates=[rate("dining", "3"), rate("other", "1")])
    b = card(name="B", rates=[rate("other", "2")])
    r1 = cards.recommend([a, b], req(monthly_spend=spend(dining=1000)), NOW)
    r2 = cards.recommend([b, a], req(monthly_spend=spend(dining=1000)), NOW)
    assert [x.product.name for x in r1.results] == [x.product.name for x in r2.results] == ["A", "B"]
    assert [x.rank for x in r1.results] == [1, 2]
    assert NOW - timedelta(0) == NOW
