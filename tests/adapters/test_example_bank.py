"""Example Bank (fictional, test_only): added via docs/ADDING_A_BANK.md using only config, adapter, fixtures, tests."""

from decimal import Decimal

import pytest

from tests.adapters._helpers import FIX, run_adapter

E = FIX / "example_bank"


@pytest.mark.parametrize(
    ("fixture", "slug", "expected"),
    [
        (
            "card_everyday_cash.html",
            "everyday-cash",
            {
                "annual_fee_cents": 0,
                "foreign_tx_fee_pct": Decimal("3"),
                "reward_currency": "cashback",
                "network": "Visa",
                "base_rate": Decimal("1"),
            },
        ),
        (
            "card_voyager_rewards.html",
            "voyager-rewards",
            {
                "annual_fee_cents": 9500,
                "intro_annual_fee_cents": 0,
                "reward_currency": "points",
                "network": "Mastercard",
                "reward_program": "Example Rewards",
                "foreign_tx_fee_pct": Decimal("0"),
            },
        ),
        (
            "card_example_air_miles.html",
            "example-air-miles",
            {
                "annual_fee_cents": 9900,
                "is_co_branded": True,
                "co_brand_partner": "Example Air",
                "reward_currency": "miles",
            },
        ),
        ("card_business_cash.html", "business-cash", {"segment": "business", "base_rate": Decimal("2")}),
        ("card_secured.html", "secured", {"is_secured": True, "secured_min_deposit_cents": 20000}),
        ("card_student_cash.html", "student-cash", {"is_student": True, "base_rate": Decimal("1.5")}),
        (
            "card_rotating_cash.html",
            "rotating-cash",
            {"annual_fee_cents": 0, "foreign_tx_fee_pct": Decimal("3")},
        ),
        (
            "checking_everyday_checking.html",
            "everyday-checking",
            {
                "monthly_fee_cents": 1200,
                "min_opening_deposit_cents": 2500,
                "account_type": "Standard checking",
            },
        ),
        (
            "checking_online_checking.html",
            "online-checking",
            {"monthly_fee_cents": 0, "min_opening_deposit_cents": 0},
        ),
        ("savings_high_yield.html", "high-yield", {"apy_pct": Decimal("4.00"), "monthly_fee_cents": 0}),
        ("savings_tiered.html", "tiered", {"monthly_fee_cents": 500, "min_opening_deposit_cents": 10000}),
    ],
)
def test_values(fixture: str, slug: str, expected: dict[str, object]) -> None:
    c = run_adapter("example_bank", E / fixture, slug)
    for k, v in expected.items():
        assert c.value(k) == v, k
    assert c.parser_version == "example_bank/1.0.0"
    assert not c.refused_fields


def test_offers_per_product() -> None:
    q = {}
    for fixture, slug in [
        ("card_everyday_cash.html", "everyday-cash"),
        ("card_voyager_rewards.html", "voyager-rewards"),
        ("card_example_air_miles.html", "example-air-miles"),
        ("card_business_cash.html", "business-cash"),
        ("card_rotating_cash.html", "rotating-cash"),
        ("card_secured.html", "secured"),
    ]:
        c = run_adapter("example_bank", E / fixture, slug)
        q[slug] = [o.value.amount_qualifier for o in c.offers if o.value]
    assert q == {
        "everyday-cash": ["exact"],
        "voyager-rewards": ["up_to"],
        "example-air-miles": ["up_to"],
        "business-cash": ["starting_at"],
        "rotating-cash": ["up_to"],
        "secured": [],
    }
