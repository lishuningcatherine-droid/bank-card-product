"""Citi adapter tests on verbatim rendered official pages (tests/fixtures/citi/RETRIEVED.txt, 2026-11-09).

Every expected value was read off the fixture's page text by hand.
"""

from decimal import Decimal

from tests.adapters._helpers import rates, run_official


def _offer(c):  # type: ignore[no-untyped-def]
    [o] = [o.value for o in c.offers if o.value]
    return o


def test_strata_premier() -> None:
    c = run_official("citi", "strata-premier", "strata-premier.html")
    assert c.parser_version == "citi/1.0.0"
    assert c.name == "Citi Strata Premier® Card"
    assert c.value("annual_fee_cents") == 9500  # "Annual Fee1" / "$95"
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("19.74"),
        Decimal("27.74"),
    )
    r = rates(c)
    assert r["hotel@portal"] == ("10x", None)  # "... booked on cititravel.com"
    assert r["airline"] == r["dining"] == r["groceries"] == r["gas"] == ("3x", None)
    assert r["other"] == ("1x", None)
    o = _offer(c)
    # "Earn 60,000 bonus points" / "after spending $4,000 in the first 3 months2"
    assert (o.amount_qualifier, o.amount_max, o.reward_unit) == ("exact", 60000, "points")
    assert (o.requirement_min_cents, o.qualification_window_count, o.qualification_window_unit) == (
        400000,
        3,
        "months",
    )
    assert o.eligibility_restrictions is not None
    assert (
        "currently have or previously had a Citi Strata Premier® or a Citi Premier® account"
        in o.eligibility_restrictions
    )


def test_double_cash() -> None:
    c = run_official("citi", "double-cash", "double-cash.html")
    assert c.name == "Citi Double Cash® Card"
    assert c.value("annual_fee_cents") == 0
    assert rates(c)["other"] == ("2pct", None)  # "Unlimited 2% cash back on purchases"
    # the "Variable APR" box is for balance transfers on this page: never read as the purchase APR
    assert c.value("purchase_apr_min_pct") is None
    o = _offer(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_count) == (
        20000,
        "cents",
        150000,
        6,
    )


def test_aadvantage_business() -> None:
    c = run_official("citi", "aadvantage-business", "aadvantage-business.html")
    assert c.value("segment") == "business"
    # "$99" / "Annual Fee, waived for the first year1"
    assert (
        c.value("annual_fee_cents"),
        c.value("intro_annual_fee_cents"),
        c.value("intro_annual_fee_months"),
    ) == (
        9900,
        0,
        12,
    )
    r = rates(c)
    assert r["partner"] == r["car_rental"] == r["gas"] == ("2x", None)
    assert r["other"] == ("1x", None)
    # "telecommunications merchants and cable and satellite providers" maps to no category: incomplete, not guessed
    assert c.value("earn_rates_complete") is None
    o = _offer(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_count) == (
        75000,
        "miles",
        500000,
        5,
    )
