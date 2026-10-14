"""U.S. Bank adapter tests on verbatim official pages (tests/fixtures/us_bank/RETRIEVED.txt, 2026-10-13).

Every expected value was read off the fixture's page text by hand.
"""

from decimal import Decimal

from bankrec.model import NullReason
from tests.adapters._helpers import rates, run_official


def _offer(c):  # type: ignore[no-untyped-def]
    [o] = [o.value for o in c.offers if o.value]
    return o


def test_altitude_connect() -> None:
    c = run_official(
        "us_bank",
        "altitude-connect-visa-signature-credit-card",
        "credit-cards-altitude-connect-visa-signature-credit-card-html.rendered.html",
    )
    assert c.parser_version == "us_bank/1.0.0"
    assert c.name == "U.S. Bank Altitude® Connect Visa Signature® Card"
    assert c.value("annual_fee_cents") == 0  # "Enjoy no annual fee and get all of these great benefits."
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("17.74"),
        Decimal("27.74"),
    )
    assert (c.value("intro_purchase_apr_pct"), c.value("intro_purchase_apr_months")) == (Decimal("0"), 15)
    assert c.value("foreign_tx_fee_pct") == Decimal("0")
    r = rates(c)
    assert r["travel"] == ("4x", None)
    assert r["gas"] == (
        "4x",
        100000,
    )  # "4X points at gas stations/EV charging stations on your first $1,000 each quarter"
    assert r["dining"] == r["streaming"] == r["groceries"] == ("2x", None)
    assert r["other"] == ("1x", None)
    o = _offer(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_days) == (
        20000,
        "points",
        100000,
        90,
    )


def test_cash_plus_rendered_fills_placeholders_and_choice_categories() -> None:
    c = run_official(
        "us_bank",
        "cash-plus-visa-signature-credit-card",
        "credit-cards-cash-plus-visa-signature-credit-card-html.rendered.html",
    )
    assert c.name == "U.S. BANK CASH+® VISA SIGNATURE® CARD"  # the page has no mixed-case spelling
    assert c.value("annual_fee_cents") == 0
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("17.99"),
        Decimal("28.24"),
    )
    r = rates(c)
    # Chosen categories are represented, never their listed examples (no fixed gas/grocery/dining 2%).
    assert (
        r
        == {
            "choice": (
                "5pct",
                200000,
            ),  # "5% ... on your first $2,000 in combined eligible purchases each quarter on two categories you choose"
            "choice_everyday": (
                "2pct",
                None,
            ),  # "2% ... on one everyday category you choose ..., like gas stations ..."
            "other": ("1pct", None),
            "travel@portal": (
                "5pct",
                None,
            ),  # "5% cash back on prepaid travel ... booked directly in the Travel Center"
        }
    )
    assert c.value("earn_rates_complete") is True
    assert (_offer(c).amount_max, _offer(c).requirement_min_cents) == (20000, 100000)


def test_cash_plus_static_placeholders_are_requires_render() -> None:
    c = run_official(
        "us_bank", "cash-plus-visa-signature-credit-card", "static-cash-plus-visa-signature-credit-card.html"
    )
    # The static page does say "Enjoy all the benefits with no annual fee", but its APR is "currently $."
    assert c.value("annual_fee_cents") == 0
    assert c.value("purchase_apr_min_pct") is None
    assert c.fields["purchase_apr_min_pct"].null_reason is NullReason.requires_render


def test_triple_cash_business() -> None:
    c = run_official(
        "us_bank",
        "business-triple-cash-back-credit-card",
        "business-banking-business-credit-cards-business-triple-cash-back-credit-card-html.rendered.html",
    )
    assert c.value("segment") == "business" and c.value("annual_fee_cents") == 0
    assert (c.value("intro_purchase_apr_months"), c.value("purchase_apr_min_pct")) == (12, Decimal("17.49"))
    r = rates(c)
    assert r["gas"] == r["dining"] == ("3pct", None) and r["other"] == ("1pct", None)
    assert [x.value.portal_only for x in c.reward_rates if x.value and x.value.category == "travel"] == [True]


def test_altitude_go_secured_deposit_and_sentence_split() -> None:
    c = run_official(
        "us_bank",
        "altitude-go-secured-visa-credit-card",
        "credit-cards-altitude-go-secured-visa-credit-card-html.rendered.html",
    )
    assert c.value("is_secured") is True and c.value("secured_min_deposit_cents") == 30000  # "$300 to $5,000"
    r = rates(c)
    # "1X Point on all other eligible purchases. Plus, a $15 credit for annual streaming ..." is not a streaming rate.
    assert r["streaming"] == ("2x", None) and r["dining"] == ("4x", 200000) and r["other"] == ("1x", None)
