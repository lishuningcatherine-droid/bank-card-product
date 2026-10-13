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


# ---- shapes seen on real issuer pages (DESIGN §24.3); statements written here, not copied from a bank


def test_each_rate_in_a_multi_rate_sentence_keeps_its_own_categories() -> None:
    r = parse_reward_statement(
        "Earn 4% on partner orders, 3% on dining, 2% at grocery stores and 1% on all other"
    )
    # "partner orders" is not a vocabulary category, and later clauses' categories are not borrowed.
    assert r is None
    r = parse_reward_statement("3% on dining, 2% at grocery stores")
    assert r is not None and r.categories == ["dining"]


def test_first_dollars_cap_and_annually() -> None:
    r = parse_reward_statement(
        "Earn 2 points for each dollar spent at gas stations on the first $5,000 in combined purchases per "
        "anniversary year"
    )
    assert r is not None and (r.rate, r.rate_unit, r.categories) == (Decimal("2"), "x", ["gas"])
    assert (r.cap_cents, r.cap_period, r.cap_combined) == (500000, "annual", True)
    r = parse_reward_statement(
        "Earn 3X points for every $1 on the first $6,000 spent in combined purchases annually"
    )
    assert r is None  # no category named → no rate
    r = parse_reward_statement(
        "Earn 3X points for every $1 on the first $6,000 spent annually at grocery stores"
    )
    assert r is not None and (r.cap_cents, r.cap_period) == (600000, "annual")


def test_singular_point_per_dollar() -> None:
    r = parse_reward_statement("Earn 1 point per $1 on all other purchases")
    assert r is not None and (r.rate, r.rate_unit, r.categories) == (Decimal("1"), "x", ["other"])


def test_narrow_categories_are_not_broad_ones() -> None:
    assert categories_in("online grocery") == ["online_grocery"]
    assert categories_in("select food delivery") == ["food_delivery"]
    assert categories_in("flights booked direct") == ["airline"]
    assert categories_in("flights") == ["airline"]


def test_issuer_portal_names_mark_portal_only() -> None:
    r = parse_reward_statement("5x points on Chase Travel")
    assert r is not None and r.portal_only is True
