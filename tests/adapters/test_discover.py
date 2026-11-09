"""Discover adapter tests on verbatim official pages (tests/fixtures/discover/RETRIEVED.txt, 2026-11-09)."""

from decimal import Decimal

from tests.adapters._helpers import rates, run_official


def test_it_cash_back() -> None:
    c = run_official("discover", "it-cash-back", "it-cash-back.html")
    assert c.parser_version == "discover/1.0.0"
    assert c.name == "Discover it Cash Back Credit Card"
    assert c.value("annual_fee_cents") == 0  # "No annual fee"
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.74"),
        Decimal("28.74"),
    )
    r = rates(c)
    assert r["rotating"] == (
        "5pct",
        None,
    )  # "... at different places you shop each quarter ... when you activate."
    assert r["other"] == ("1pct", None)
    [o] = [o.value for o in c.offers if o.value]
    # the footnote with the full terms, never the FAQ's "So if you earn $50 cash back, we'll give you another $50."
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_count) == (
        20000,
        "cents",
        50000,
        3,
    )
    assert "in the past 48 months" in o.verbatim_text


def test_it_miles_has_no_fixed_offer() -> None:
    c = run_official("discover", "it-miles", "it-miles.html")
    assert c.name == "Discover it Miles Credit Card"
    assert rates(c)["other"] == ("1.5x", None)
    # the first-year miles match states no amount: not a fixed-amount offer
    assert c.offers == []
