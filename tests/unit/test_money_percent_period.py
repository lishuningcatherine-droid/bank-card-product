from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bankrec.parsers.money import find_amounts, parse_fee_schedule, parse_money
from bankrec.parsers.percent import parse_percent, parse_percent_range
from bankrec.parsers.period import parse_period


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("$95", 9500),
        ("$1,250.50", 125050),
        ("$0", 0),
        ("No annual fee", 0),
        ("$95 annual fee", 9500),
        ("Annual fee: $550", 55000),
        ("none", 0),
        ("$5k", 500000),
        ("$12.5", 1250),
    ],
)
def test_parse_money(text: str, cents: int) -> None:
    assert parse_money(text) == cents


@pytest.mark.parametrize("text", ["$", "NaN", "", "  ", "--", "{{fee}}", "Loading...", "see terms"])
def test_parse_money_refuses_placeholders_and_non_numbers(text: str) -> None:
    assert parse_money(text) is None


def test_marketing_aggregate_is_never_a_value() -> None:
    assert find_amounts("Get more than $1,500 in annual value with this card") == []
    assert parse_money("more than $1,000 in value") is None


def test_fee_schedule_intro_then() -> None:
    s = parse_fee_schedule("$0 intro annual fee for the first year, then $95")
    assert (s.intro_cents, s.ongoing_cents) == (0, 9500)
    assert parse_fee_schedule("$95").ongoing_cents == 9500
    assert parse_fee_schedule("$").ongoing_cents is None


@given(st.integers(min_value=0, max_value=10_000_000), st.text(alphabet="abc :;\n", max_size=20))
def test_money_roundtrip(dollars: int, noise: str) -> None:
    assert parse_money(f"{noise}${dollars:,}{noise}") == dollars * 100


@given(st.text(alphabet=st.characters(blacklist_characters="$0123456789"), max_size=60))
def test_money_without_digits_never_invents(text: str) -> None:
    v = parse_money(text)
    assert v in (None, 0)
    if v == 0:  # only explicit zero phrases may yield 0
        assert any(p in text.lower() for p in ("no annual fee", "no monthly", "no foreign", "no fee", "none"))


def test_percent_and_ranges() -> None:
    assert parse_percent("4.25% APY") == Decimal("4.25")
    assert parse_percent("NaN% APY") is None
    r = parse_percent_range("20.24% - 29.24% Variable")
    assert r is not None and (r.low, r.high, r.variable) == (Decimal("20.24"), Decimal("29.24"), True)
    r = parse_percent_range("29.99%")
    assert r is not None and r.low == r.high == Decimal("29.99")
    assert parse_percent_range("Prime + 12.99%") is None
    assert parse_percent_range("$") is None
    r = parse_percent_range("30% to 20%")
    assert r is not None and r.low < r.high


@given(st.decimals(min_value=0, max_value=40, places=2), st.decimals(min_value=0, max_value=40, places=2))
def test_percent_range_property(a: Decimal, b: Decimal) -> None:
    r = parse_percent_range(f"{a}% - {b}% Variable")
    assert r is not None and r.low == min(a, b) and r.high == max(a, b) and r.variable


@pytest.mark.parametrize(
    ("text", "value", "unit", "days"),
    [
        ("in the first 3 months", 3, "months", None),  # never converted to 90 days
        ("within 90 days", 90, "days", 90),
        ("15 billing cycles", 15, "billing_cycles", None),
        ("first two years", 2, "years", None),
        ("ninety days", 90, "days", 90),
    ],
)
def test_period(text: str, value: int, unit: str, days: int | None) -> None:
    p = parse_period(text)
    assert p is not None and (p.value, p.unit, p.days) == (value, unit, days)


def test_period_none() -> None:
    assert parse_period("whenever") is None
    assert parse_period("0 days") is None


@given(
    st.integers(min_value=1, max_value=999), st.sampled_from(["days", "months", "years", "billing cycles"])
)
def test_period_property(n: int, unit: str) -> None:
    p = parse_period(f"for {n} {unit}")
    assert p is not None and p.value == n


def test_period_units_are_never_converted() -> None:
    # spot-check round 2 (C): "3 months" is not 90 days, "15 billing cycles" is not 15 months
    m, d, c = (
        parse_period("first 3 months"),
        parse_period("within 90 days"),
        parse_period("15 billing cycles"),
    )
    assert m is not None and (m.value, m.unit, m.days, m.months) == (3, "months", None, 3)
    assert d is not None and (d.value, d.unit, d.days, d.months) == (90, "days", 90, None)
    assert c is not None and (c.value, c.unit, c.days, c.months) == (15, "billing_cycles", None, None)
