from datetime import date
from decimal import Decimal

from bankrec.normalize.categories import categories_in, normalize_category
from bankrec.parsers.rewards import parse_reward_statement


def test_cap_combined_post_cap() -> None:
    r = parse_reward_statement(
        "2% cash back at grocery stores on up to $2,000 in combined purchases each quarter, then 1%"
    )
    assert r is not None
    assert (r.rate, r.rate_unit, r.categories) == (Decimal("2"), "pct", ["groceries"])
    assert (r.cap_cents, r.cap_period, r.cap_combined, r.post_cap_rate) == (
        200000,
        "quarterly",
        True,
        Decimal("1"),
    )


def test_annual_cap() -> None:
    r = parse_reward_statement(
        "Earn 6% cash back at U.S. supermarkets on up to $6,000 per year in purchases (then 1%)"
    )
    assert (
        r is not None
        and r.cap_cents == 600000
        and r.cap_period == "annual"
        and r.post_cap_rate == Decimal("1")
    )


def test_rotating_activation() -> None:
    r = parse_reward_statement(
        "5% cash back on up to $1,500 in combined purchases in bonus categories each quarter you activate"
    )
    assert r is not None and r.is_rotating and r.requires_activation and r.categories == ["rotating"]
    assert r.post_cap_rate is None and r.notes


def test_portal_only_and_time_bound() -> None:
    r = parse_reward_statement("5X points on travel booked through the Example Bank Travel Center")
    assert r is not None and r.portal_only and r.rate_unit == "x"
    t = parse_reward_statement("2X points on gas stations through December 31, 2026")
    assert t is not None and t.ends_on == date(2026, 12, 31)


def test_base_rate() -> None:
    r = parse_reward_statement("Unlimited 1.5% cash back on all purchases")
    assert r is not None and r.is_base and r.categories == ["other"] and r.rate == Decimal("1.5")


def test_miles_per_dollar_and_none() -> None:
    r = parse_reward_statement("Earn 2 miles per $1 on airline purchases")
    assert r is not None and r.rate == Decimal("2") and r.categories == ["airline"]
    assert parse_reward_statement("Great rewards for you") is None
    assert parse_reward_statement("NaN% cash back on dining") is None


def test_categories_vocabulary() -> None:
    assert categories_in("3% on dining and drugstores") == ["dining", "drugstores"]
    assert categories_in("U.S. supermarkets") == ["groceries"]
    assert normalize_category("gas stations") == ("gas", True)
    assert normalize_category("yacht charters") == ("other", False)
