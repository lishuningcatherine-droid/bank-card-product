"""American Express adapter tests on verbatim rendered pages (tests/fixtures/american_express/RETRIEVED.txt, 2026-10-13).

Every expected value was read off the fixture's page text by hand.
"""

from decimal import Decimal

from bankrec.model import NullReason
from tests.adapters._helpers import rates, run_official

OFFER_NOTE = "Offers may vary; confirm on American Express at application"


def test_blue_cash_preferred() -> None:
    c = run_official(
        "american_express", "blue-cash-preferred", "us-credit-cards-card-blue-cash-preferred.rendered.html"
    )
    assert c.parser_version == "american_express/1.0.0"
    assert c.name == "Blue Cash Preferred® Card"
    # "Annual Fee: $0 intro annual fee for the first year, then $95"
    assert (c.value("intro_annual_fee_cents"), c.value("annual_fee_cents")) == (0, 9500)
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("19.74"),
        Decimal("28.74"),
    )
    # "0% intro APR for up to 18 months ... may be as short as 6 months": the duration is not a fixed value.
    assert c.fields["intro_purchase_apr_months"].null_reason is NullReason.ambiguous
    assert c.value("network") == "American Express" and c.value("reward_currency") == "cashback"
    assert rates(c) == {
        "groceries": ("6pct", 600000),  # "On up to $6,000 per year in purchases at U.S. supermarkets"
        "streaming": ("6pct", None),
        "transit": ("3pct", None),
        "gas": ("3pct", None),
        "other": ("1pct", None),
    }
    [o] = [o.value for o in c.offers if o.value]
    assert (
        o.amount_qualifier,
        o.amount_max,
        o.reward_unit,
        o.requirement_min_cents,
        o.qualification_window_days,
    ) == (
        "exact",
        25000,
        "cents",
        300000,
        180,
    )
    assert o.note == OFFER_NOTE


def test_gold_card_k_caps_and_absent_offer() -> None:
    c = run_official("american_express", "gold-card", "us-credit-cards-card-gold-card.rendered.html")
    assert c.value("annual_fee_cents") == 32500
    r = rates(c)
    # "on up to $50K in purchases per calendar year" / "on up to $25K ..."
    assert r["dining"] == ("4x", 5000000) and r["groceries"] == ("4x", 2500000)
    assert all(
        x.value.portal_only for x in c.reward_rates if x.value and x.value.category in {"hotel", "travel"}
    )
    assert not [o for o in c.offers if o.value]
    assert c.offer_absent_note == "Check American Express for the current welcome offer"


def test_marriott_bevy_combined_cap_with_us_abbreviation() -> None:
    c = run_official(
        "american_express", "marriott-bonvoy-bevy", "us-credit-cards-card-marriott-bonvoy-bevy.rendered.html"
    )
    assert c.value("co_brand_partner") == "Marriott" and c.value("annual_fee_cents") == 25000
    assert c.value("foreign_tx_fee_pct") == Decimal("0")
    assert c.value("purchase_apr_min_pct") == Decimal(
        "19.74"
    )  # "APR: 19.74% to 28.74% variable APR on purchases."
    r = rates(c)
    # "(on up to $15,000 in combined purchases at restaurants and U.S. supermarkets per calendar year ...)"
    assert r["dining"] == r["groceries"] == ("4x", 1500000)
    assert r["hotel"] == ("6x", None)
