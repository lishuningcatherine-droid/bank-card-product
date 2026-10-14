"""Regression tests for the owner's spot check, round 1 (docs/SPOT_CHECK_TRIAGE.md), built from the stored snapshots.

Each test names its finding. Values were read off the snapshot text by hand.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bankrec.model import NullReason, OfferRec, OfferTier
from bankrec.recommend import cards
from bankrec.recommend.models import MonthlySpend
from tests.adapters._helpers import rates, run_official
from tests.unit.test_recommend_cards import NOW, card, req


def offers(c):  # type: ignore[no-untyped-def]
    return [o.value for o in c.offers if o.value]


def test_f1_sapphire_preferred_bonus_is_75000_and_portal_5x_is_kept() -> None:
    c = run_official(
        "chase", "chase-sapphire-preferred", "creditcards-rewards-credit-cards-sapphire-preferred.html"
    )
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_days) == (
        75000,
        "points",
        500000,
        90,
    )
    assert "60,000" not in o.verbatim_text  # the page's only 60,000 is "$60,000" of auto rental coverage
    r = rates(c)
    assert r["travel@portal"] == ("5x", None) and r["travel"] == ("2x", None)
    assert c.value("earn_rates_complete") is True


def test_f2_ink_business_cash_5pct_business_categories() -> None:
    c = run_official("chase", "ink-business-cash", "creditcards-business-credit-cards-ink-cash.html")
    r = rates(c)
    # "Earn 5% cash back on the first $25,000 spent in combined purchases at office supply stores and on internet,
    # cable and phone services each account anniversary year"
    assert r["office_supply"] == r["telecom"] == ("5pct", 2500000)
    assert c.value("earn_rates_complete") is True


def test_f3_venture_x_uncaptured_offer_is_not_reported_as_none() -> None:
    c = run_official("capital_one", "venture-x", "www-credit-cards-venture-x.html")
    assert offers(c) == []
    assert (
        c.fields["offer_capture"].null_reason is NullReason.not_applicable
    )  # no offer text in the static HTML
    assert c.offer_absent_note is not None and "not captured" in c.offer_absent_note
    r = rates(c)
    assert (
        r["hotel@portal"] == ("10x", None)
        and r["airline@portal"] == ("5x", None)
        and r["other"] == ("2x", None)
    )


def test_f4_savor_apr_is_the_captured_value_and_categories_are_complete() -> None:
    c = run_official("capital_one", "savor", "www-credit-cards-savor.html")
    # The snapshot (2026-10-13) says "18.74% - 28.74%"; a different live value is a page change, caught on recapture.
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.74"),
        Decimal("28.74"),
    )
    r = rates(c)
    assert r["groceries"] == r["dining"] == r["entertainment"] == r["streaming"] == ("3pct", None)
    assert r["other"] == ("1pct", None) and c.value("earn_rates_complete") is True


def test_f5_customized_cash_choice_category_and_200_bonus() -> None:
    c = run_official(
        "bank_of_america",
        "cash-back-credit-card",
        "credit-cards-products-cash-back-credit-card.rendered.html",
    )
    [o] = offers(c)
    assert o.amount_max == 20000  # "Online $200 cash rewards bonus"
    r = rates(c)
    assert r["choice"] == (
        "3pct",
        250000,
    )  # "3% cash back ... in the category of your choice", shared $2,500/quarter
    assert r["groceries"] == r["wholesale_clubs"] == ("2pct", 250000) and r["other"] == ("1pct", None)


def test_f5_unlimited_cash_is_a_different_card_with_250() -> None:
    c = run_official(
        "bank_of_america",
        "unlimited-cash-back-credit-card",
        "credit-cards-products-unlimited-cash-back-credit-card.rendered.html",
    )
    [o] = offers(c)
    assert o.amount_max == 25000 and o.offer_url.endswith("/unlimited-cash-back-credit-card/")
    assert rates(c) == {"other": ("1.5pct", None)}


def test_f6_premium_rewards_unchanged() -> None:
    c = run_official(
        "bank_of_america",
        "premium-rewards-credit-card",
        "credit-cards-products-premium-rewards-credit-card.rendered.html",
    )
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (60000, "points", 400000)
    assert rates(c) == {"travel": ("2x", None), "dining": ("2x", None), "other": ("1.5x", None)}


def test_f7_altitude_connect_intro_keeps_billing_cycles() -> None:
    c = run_official(
        "us_bank",
        "altitude-connect-visa-signature-credit-card",
        "credit-cards-altitude-connect-visa-signature-credit-card-html.rendered.html",
    )
    assert c.value("intro_purchase_apr_months") == 15
    assert (
        c.value("intro_apr_period_unit") == "billing_cycles"
    )  # "for the first 15 billing cycles", not months
    r = rates(c)
    assert r["travel"] == ("4x", None) and r["gas"] == ("4x", 100000) and r["other"] == ("1x", None)


def test_f8_triple_cash_bonus_requirement_from_footnote_and_business_categories() -> None:
    c = run_official(
        "us_bank",
        "business-triple-cash-back-credit-card",
        "business-banking-business-credit-cards-business-triple-cash-back-credit-card-html.rendered.html",
    )
    [o] = offers(c)
    # "Get rewarded with a $750 cash back bonus." + "... Net Purchases totaling $6,000 or more ... within 180 days"
    assert (o.amount_qualifier, o.amount_max, o.requirement_min_cents, o.qualification_window_days) == (
        "exact",
        75000,
        600000,
        180,
    )
    r = rates(c)
    assert r["gas"] == r["dining"] == r["office_supply"] == r["telecom"] == ("3pct", None)


def test_f9_hilton_honors_gas_and_other_and_no_current_offer() -> None:
    c = run_official("american_express", "hilton-honors", "static-hilton-honors.html")
    r = rates(c)
    assert r["gas"] == ("5x", None) and r["other"] == ("3x", None) and r["hotel"] == ("7x", None)
    assert (
        offers(c) == []
    )  # the dated 100,000-point offer is not on the captured page; nothing shown as current
    assert c.offer_absent_note == "Check American Express for the current welcome offer"


def test_f10_brilliant_2x_other() -> None:
    c = run_official("american_express", "marriott-bonvoy-brilliant", "static-marriott-bonvoy-brilliant.html")
    assert rates(c)["other"] == ("2x", None)


def test_f10_tiered_offer_schema_and_scoring() -> None:
    """Synthetic (Example Bank wording): 100,000 after $6,000 + 50,000 after an additional $2,000, within 6 months."""
    rec = OfferRec(
        offer_type="card_welcome",
        reward_unit="points",
        amount_qualifier="tiered",
        amount_min=100000,
        amount_max=150000,
        offer_url="https://www.examplebank.example/x",
        verbatim_text="Earn up to 150,000 points ...",
        tiers=[
            OfferTier(amount=100000, requirement_min_cents=600000, window_days=180, text="..."),
            OfferTier(
                amount=50000, requirement_min_cents=200000, window_days=180, incremental=True, text="..."
            ),
        ],
    )
    assert rec.amount_max == 150000
    o = {**_offer_view(rec)}
    p = card(offers=[_view(o)])
    # $1,200/month × 6 months = $7,200: reaches the first tier ($6,000), not the cumulative $8,000
    low = cards.recommend(
        [p], req(goal="welcome_bonus", monthly_spend=MonthlySpend(other=1200)), NOW
    ).results[0]
    high = cards.recommend(
        [p], req(goal="welcome_bonus", monthly_spend=MonthlySpend(other=1500)), NOW
    ).results[0]
    assert low.values.promotional_cents == 100000 and high.values.promotional_cents == 150000


def _offer_view(rec: OfferRec) -> dict:  # type: ignore[type-arg]
    d = rec.model_dump()
    d["tiers"] = [t.model_dump() for t in rec.tiers]
    return d


def _view(d: dict):  # type: ignore[no-untyped-def,type-arg]
    from tests.unit.test_recommend_cards import offer

    return offer(
        amount_qualifier=d["amount_qualifier"],
        amount_min=d["amount_min"],
        amount_max=d["amount_max"],
        reward_unit=d["reward_unit"],
        tiers=d["tiers"],
        requirement_type=None,
        requirement_min_cents=None,
    )


_ = (datetime, UTC)


def test_d_chase_new_template_avios_offer_and_all_rates() -> None:
    """Found re-running ingestion (step D): Chase's new page template puts the offer in data-slot="hero-offer", and
    "In addition earn 2 Avios ..." / "3 Avios for every $1" were invisible to the completeness check."""
    c = run_official("chase", "british-airways-visa-signature", "british-airways-new-template.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (75000, "points", 500000)
    assert rates(c) == {"airline": ("3x", None), "hotel": ("2x", None), "other": ("1x", None)}
    assert c.value("earn_rates_complete") is True


def test_d_partner_purchases_with_parenthetical_are_a_partner_rate() -> None:
    # "3 points per $1 spent on Allegiant purchases (air, hotel, car rental and attractions)"
    c = run_official("bank_of_america", "allegiant-credit-card", "allegiant-2026-10-14.rendered.html")
    assert rates(c) == {"partner": ("3x", None), "dining": ("2x", None), "other": ("1x", None)}
    assert c.value("earn_rates_complete") is True


def test_d_categories_listed_beside_the_partner_stand() -> None:
    # "Earn 3 points for every $1 spent on eligible dining, foreign transaction, Alaska Airlines and Hawaiian
    # Airlines purchases": dining and foreign purchases are general rates, the airlines part is a partner rate.
    c = run_official(
        "bank_of_america", "alaska-airlines-infinite-credit-card", "atmos-summit-2026-10-14.rendered.html"
    )
    r = rates(c)
    assert r["dining"] == r["foreign_purchases"] == r["partner"] == ("3x", None) and r["other"] == (
        "1x",
        None,
    )


def test_d_royal_one_plus_lists_every_2x_category_and_partner_4x() -> None:
    # "2 points per dollar spent on eligible airline, hotel, dining, grocery, gas and EV charging station purchases"
    c = run_official(
        "bank_of_america", "royal-one-plus-credit-card", "royal-one-plus-2026-10-14.rendered.html"
    )
    r = rates(c)
    for k in ("airline", "hotel", "dining", "groceries", "gas", "ev_charging"):
        assert r[k] == ("2x", None), k
    assert r["partner"] == ("4x", None) and r["other"] == ("1x", None)


def test_d_glued_footnote_marker_keeps_the_capped_choice_rate() -> None:
    # "5% cash back2on your first $2,000 in combined eligible purchases each quarter in two categories you choose3"
    c = run_official(
        "us_bank", "cash-plus-secured-visa-credit-card", "cash-plus-secured-2026-10-14.rendered.html"
    )
    r = rates(c)
    assert (
        r["choice"] == ("5pct", 200000)
        and r["choice_everyday"] == ("2pct", None)
        and r["other"] == ("1pct", None)
    )
    assert c.value("earn_rates_complete") is True


def test_d_fee_and_apr_lines_are_not_earn_statements() -> None:
    from bankrec.parsers.rewards import parse_reward_statement

    assert parse_reward_statement("3% foreign transaction fee") is None
