"""Chase adapter tests on verbatim official pages (tests/fixtures/chase/RETRIEVED.txt, retrieved 2026-10-13).

Every expected value below was read off the page text of the fixture by hand. The adapter's generic logic is also
exercised on synthetic Example Bank pages (placeholders).
"""

from decimal import Decimal

import pytest

from bankrec.ingest.common.html import parse_html, scoped
from bankrec.model import NullReason
from tests.adapters._helpers import FIX, rates, run_adapter, run_official

C = FIX / "chase"


def test_sapphire_preferred() -> None:
    c = run_official(
        "chase", "chase-sapphire-preferred", "creditcards-rewards-credit-cards-sapphire-preferred.html"
    )
    assert c.parser_version == "chase/1.0.0"
    assert c.name == "Chase Sapphire Preferred® Credit Card"
    # The site header's "No Annual Fee (15)" filter label must not be read as this card's fee.
    assert c.value("annual_fee_cents") == 9500
    assert c.fields["annual_fee_cents"].span_text == "$95 annual fee†"
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("19.49"),
        Decimal("27.74"),
    )
    assert c.value("purchase_apr_variable") is True
    assert c.value("foreign_tx_fee_pct") == Decimal("0")
    assert c.value("segment") == "consumer" and c.value("is_co_branded") is False
    assert c.value("reward_currency") == "points" and c.value("base_rate") == Decimal("1")
    assert rates(c) == {
        "travel": ("2x", None),  # "2x points on all other travel"; the 5x Chase Travel rate is portal-only
        "dining": ("3x", None),
        "gas": ("3x", None),
        "ev_charging": ("3x", None),
        "streaming": ("3x", None),
        "online_grocery": ("3x", None),  # "online grocery" is not groceries in general
        "other": ("1x", None),
    }
    assert [r.value.portal_only for r in c.reward_rates if r.value and r.value.category == "travel"] == [
        False
    ]
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_qualifier, o.amount_max, o.reward_unit) == ("exact", 75000, "points")
    assert (o.requirement_type, o.requirement_min_cents, o.qualification_window_days) == ("spend", 500000, 90)


def test_freedom_unlimited_has_no_fee_claim_from_tag_cloud() -> None:
    c = run_official(
        "chase", "chase-freedom-unlimited", "creditcards-cash-back-credit-cards-freedom-unlimited.html"
    )
    assert c.value("annual_fee_cents") == 0
    assert c.value("intro_purchase_apr_pct") == Decimal("0") and c.value("intro_purchase_apr_months") == 15
    assert c.value("intro_bt_apr_months") == 15
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.49"),
        Decimal("27.99"),
    )
    # The page never states this card's foreign transaction fee; "No Foreign Transaction Fees" appears only as a
    # category link in the browse-cards block, which is excluded.
    assert c.value("foreign_tx_fee_pct") is None
    assert c.value("base_rate") == Decimal("1.5") and c.value("reward_currency") == "cashback"
    assert rates(c) == {
        "other": ("1.5pct", None),
        "dining": ("3pct", None),
        "drugstores": ("3pct", None),
        "travel": ("5pct", None),
    }
    assert [r.value.portal_only for r in c.reward_rates if r.value and r.value.category == "travel"] == [True]
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_qualifier, o.amount_max, o.reward_unit, o.requirement_min_cents) == (
        "exact",
        20000,
        "cents",
        50000,
    )


def test_freedom_flex_struck_out_amount_is_ignored() -> None:
    c = run_official("chase", "chase-freedom-flex", "creditcards-cash-back-credit-cards-freedom-flex.html")
    # Headline "Earn a $200 [struck] $250 bonus": only the current $250 counts.
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_qualifier, o.amount_max, o.requirement_min_cents) == ("exact", 25000, 50000)
    # Rotating 5% categories: the page states no cap next to them, so the rate is left out rather than uncapped.
    assert "rotating" not in rates(c)
    assert c.value("foreign_tx_fee_pct") == Decimal(
        "0"
    )  # "Now enjoy all this with no foreign transaction fee.†"


def test_ink_business_cash_caps() -> None:
    c = run_official("chase", "ink-business-cash", "creditcards-business-credit-cards-ink-cash.html")
    assert c.value("segment") == "business"
    assert c.value("annual_fee_cents") == 0
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("16.99"),
        Decimal("24.99"),
    )
    r = rates(c)
    # "2% cash back on the first $25,000 spent in combined purchases at gas stations and restaurants each account
    # anniversary year" wins over the uncapped summary "2% cash back on dining and gas".
    assert r["gas"] == ("2pct", 2500000) and r["dining"] == ("2pct", 2500000)
    assert r["other"] == ("1pct", None)
    caps = [x.value for x in c.reward_rates if x.value and x.value.category == "gas"]
    assert caps[0].cap_period == "annual" and caps[0].cap_combined is True
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_days) == (
        75000,
        "cents",
        600000,
        90,
    )


def test_united_explorer_co_brand_and_intro_fee() -> None:
    c = run_official(
        "chase", "united-explorer", "creditcards-travel-credit-cards-united-united-explorer.html"
    )
    assert c.name == "United℠ Explorer Card"  # <sup>SM</sup> rendered as ℠
    assert c.value("is_co_branded") is True and c.value("co_brand_partner") == "United"
    assert c.value("intro_annual_fee_cents") == 0 and c.value("annual_fee_cents") == 15000
    assert c.value("intro_annual_fee_months") == 12
    assert c.value("reward_currency") == "miles"
    r = rates(c)
    # "9x total miles on eligible United flights" stacks MileagePlus earn and is left out.
    assert "airline" not in r and "travel" not in r
    assert r["hotel"] == ("2x", None) and r["dining"] == ("2x", None) and r["other"] == ("1x", None)
    # "Earn up to 80,000 bonus miles" is up_to and contributes $0.
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_qualifier, o.amount_min, o.amount_max, o.reward_unit) == ("up_to", None, 80000, "miles")


def test_marriott_boundless_annual_cap_and_hotel_partner() -> None:
    c = run_official(
        "chase", "marriott-bonvoy-boundless", "creditcards-travel-credit-cards-marriott-bonvoy-boundless.html"
    )
    assert c.value("co_brand_partner") in {"Marriott", "Bonvoy"}
    assert c.value("annual_fee_cents") == 9500
    r = rates(c)
    assert r["hotel"] == ("6x", None)  # "6X points ... at over 7,000 hotels participating in Marriott Bonvoy"
    assert r["groceries"] == r["gas"] == r["dining"] == ("3x", 600000)  # "on the first $6,000 ... annually"
    assert r["other"] == ("2x", None)
    # "Earn 3 Free Night Awards" is not a cash or points bonus.
    assert not [o for o in c.offers if o.value]


def test_sapphire_reserve_for_business_name_and_pay_in_full() -> None:
    c = run_official(
        "chase", "sapphire-reserve-for-business", "creditcards-business-credit-cards-sapphire-reserve.html"
    )
    assert c.name == "Sapphire Reserve for Business℠ Credit Card"  # not the stylised h1 "SAPPHIRE RESERVE"
    assert c.value("segment") == "business"
    assert c.value("annual_fee_cents") == 79500
    assert c.value("purchase_apr_min_pct") is None  # a pay-in-full card: the page states no APR
    [o] = [o.value for o in c.offers if o.value]
    # "Earn [150,000 struck] 200,000 points after you spend $30,000 ... in your first 6 months"
    assert (o.amount_max, o.requirement_min_cents, o.qualification_window_months) == (200000, 3000000, 6)


def test_doordash_multi_rate_sentence_and_non_cash_offer() -> None:
    c = run_official(
        "chase", "doordash-rewards-mastercard", "creditcards-cash-back-credit-cards-doordash.html"
    )
    assert c.value("network") == "Mastercard"
    r = rates(c)
    # "4% on DoorDash and Caviar orders, 3% on dining ..., 2% on grocery stores ..., and 1% on all other": each
    # category gets its own rate (merchant-only 4% has no category).
    assert r == {"dining": ("3pct", None), "groceries": ("2pct", None), "other": ("1pct", None)}
    # "a free year of DashPass that will auto-renew at $96/yr" is not a welcome bonus.
    assert not [o for o in c.offers if o.value]


def test_slate_edge_without_rewards() -> None:
    c = run_official("chase", "slate-edge", "creditcards-credit-building-credit-cards-edge.html")
    assert c.value("annual_fee_cents") == 0
    assert c.value("purchase_apr_min_pct") == c.value("purchase_apr_max_pct") == Decimal("29.24")
    assert c.reward_rates == [] and c.value("reward_currency") is None


@pytest.mark.parametrize("fixture", sorted(p.name for p in C.glob("*.html")))
def test_scope_excludes_navigation(fixture: str) -> None:
    doc = scoped(parse_html((C / fixture).read_text()), "main", ".cmp-browsecards, nav, header, footer")
    assert "No Annual Fee (15)" not in doc.text and "Visa (35)" not in doc.text


def test_logic_on_synthetic_placeholders() -> None:
    s = run_adapter("chase", FIX / "example_bank" / "pages" / "savings_static_nan.html", "high-yield")
    assert s.fields["apy_pct"].null_reason is NullReason.requires_render


def test_new_card_marketplace_template() -> None:
    """Some Chase cards switched (2026-10-13) to a template with label and value on one line: "ANNUAL FEE$0†"."""
    c = run_official("chase", "instacart-mastercard", "instacart-new-template.rendered.html")
    assert c.value("annual_fee_cents") == 0
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.49"),
        Decimal("27.99"),
    )
    assert rates(c)["other"] == ("1pct", None)
    # "Get a $50 Instacart credit automatically upon approval" is not a cash or points welcome bonus.
    assert not [o for o in c.offers if o.value]
