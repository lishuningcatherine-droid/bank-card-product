"""Regression tests for the owner's spot check, round 2 (docs/SPOT_CHECK.md round 2, DESIGN §24.17), built from the
stored snapshots of 2026-10-14. Each test names its finding; values were read off the snapshot text by hand."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from bankrec.ingest.common import extract as X
from bankrec.ingest.common.html import parse_html
from bankrec.model import NullReason
from bankrec.parsers.rewards import parse_reward_statement
from bankrec.recommend import cards
from bankrec.recommend.models import MonthlySpend, RateConditionView, RateView
from tests.adapters._helpers import run_official
from tests.unit.test_recommend_cards import NOW, card, rate, req


def offers(c):  # type: ignore[no-untyped-def]
    return [o.value for o in c.offers if o.value]


def window(o):  # type: ignore[no-untyped-def]
    return (o.qualification_window_count, o.qualification_window_unit, o.qualification_window_days)


def test_c_sapphire_reserve_window_stays_3_months() -> None:
    # «Earn 100,000 points after you spend $6,000 in purchases in the first 3 months from account opening»
    c = run_official("chase", "chase-sapphire-reserve", "sapphire-reserve-2026-10-14.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.requirement_min_cents) == (100000, 600000)
    assert window(o) == (3, "months", None) and o.qualification_window_months == 3


def test_c_quicksilver_student_window_stays_3_months() -> None:
    # «Earn a one-time $50 cash bonus once you spend $100 on purchases within 3 months from account opening»
    c = run_official("capital_one", "quicksilver-student", "quicksilver-student-2026-10-14.html")
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (5000, "cents", 10000)
    assert window(o) == (3, "months", None)


def test_c_ihg_window_stays_3_months() -> None:
    # «Earn 125,000 Bonus Points after you spend $2,000 on purchases in the first 3 months from account opening.»
    c = run_official("chase", "ihg-one-rewards", "ihg-one-rewards-2026-10-14.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.requirement_min_cents) == (125000, 200000)
    assert window(o) == (3, "months", None)


def test_d_savor_good_credit_no_offer_is_stated_by_issuer() -> None:
    # «You’ll earn the usual Savor grocery store, dining and entertainment rewards, but won’t be eligible for new
    # cardmember bonus cash or 0% intro APR»: a stated absence, not "not captured".
    c = run_official("capital_one", "savor-good-credit", "savor-good-credit-2026-10-14.html")
    assert offers(c) == [] and c.offer_status == "none_stated"
    cap = c.fields["offer_capture"]
    assert (
        cap.value is True
        and cap.span_text is not None
        and "won’t be eligible for new cardmember bonus" in cap.span_text
    )
    assert c.offer_absent_note is not None and c.offer_absent_note.startswith(
        "No welcome offer (stated by Capital One)"
    )
    assert c.fields["intro_purchase_apr_pct"].null_reason is NullReason.not_applicable


def test_d_eligibility_rules_are_not_a_stated_absence() -> None:
    assert (
        X.no_offer_statement(
            "The new cardmember bonus may not be available to you if you previously held this card."
        )
        is None
    )
    assert X.no_offer_statement("You are not eligible for a welcome offer if you have had this Card.") is None
    assert (
        X.no_offer_statement("This card does not offer a welcome bonus.")
        == "This card does not offer a welcome bonus."
    )


def test_e_surpass_no_ftf_from_faq_answer() -> None:
    # The FAQ answer is a collapsed accordion panel (aria-hidden until opened): «The Hilton Honors American Express
    # Surpass® Card does not have foreign transaction fees.» Stored before as "see issuer".
    c = run_official("american_express", "hilton-honors-surpass", "hilton-surpass-2026-10-14.html")
    f = c.fields["foreign_tx_fee_pct"]
    assert f.value == Decimal("0")
    assert (
        f.span_text is not None and "Surpass® Card" in f.span_text and "foreign transactions" in f.span_text
    )


def test_e_no_ftf_sentence_must_name_the_card() -> None:
    text = "Explore cards with no foreign transaction fees.\nThe Example Bank Voyager Card has no foreign transaction fees."
    assert X.stated_no_ftf(text, "Example Bank Voyager® Card") == (
        "The Example Bank Voyager Card has no foreign transaction fees."
    )
    assert X.stated_no_ftf(text, "Example Bank Cash Card") is None


def test_e_accordion_panels_are_text_but_hidden_tabs_are_not() -> None:
    html = (
        "<main><button aria-controls='faq1' aria-expanded='false'>Does it have fees?</button>"
        "<div id='faq1' aria-hidden='true' style='height:0px'>It has no annual fee.</div>"
        "<button role='tab' aria-controls='tab2' aria-expanded='false'>Other card</button>"
        "<div id='tab2' hidden>Other card: $95 annual fee.</div>"
        "<div role='region' aria-labelledby='h3' aria-hidden='true'>Region answer.</div></main>"
    )
    t = parse_html(html).text
    assert "It has no annual fee." in t and "Region answer." in t and "$95" not in t


def test_f_altitude_go_secured_deposit_range() -> None:
    # «Start with a security deposit of $300 to $5,000 and enjoy $0 annual fee.»
    c = run_official(
        "us_bank", "altitude-go-secured-visa-credit-card", "altitude-go-secured-2026-10-14.rendered.html"
    )
    assert c.value("is_secured") is True
    assert (c.value("secured_min_deposit_cents"), c.value("secured_max_deposit_cents")) == (30000, 500000)


def test_f_deposit_range_forms() -> None:
    assert X.deposit_range(
        "A minimum security deposit of $200 (maximum of $5,000) is required to open this account."
    )[:2] == (20000, 500000)
    lo, hi, _, note = X.deposit_range(
        "You can raise your initial credit line by depositing more than the minimum amount (up to a maximum limit of $1000)."
    )
    assert (lo, hi) == (None, None) and note is not None and "unclear" in note


def test_f_secured_deposits_are_key_fields_and_not_applicable_when_unsecured() -> None:
    from bankrec.validation.rules import policy

    assert {"secured_min_deposit_cents", "secured_max_deposit_cents"} <= set(policy()["key"]["credit_card"])
    c = run_official("chase", "chase-sapphire-reserve", "sapphire-reserve-2026-10-14.rendered.html")
    for f in ("secured_min_deposit_cents", "secured_max_deposit_cents"):
        assert c.fields[f].null_reason is NullReason.not_applicable


def conds(c, cat, rate=None):  # type: ignore[no-untyped-def]
    """{kind: text} of the conditions on the ``cat`` rate (the one with ``rate`` when given)."""
    [v] = [
        r.value
        for r in c.reward_rates
        if r.value and r.value.category == cat and (rate is None or r.value.rate == Decimal(rate))
    ]
    return {x.kind: x.text for x in v.conditions}


def test_a_sapphire_reserve_booked_direct_and_portal_qualifiers() -> None:
    # «4x points on flights booked direct*» / «4x points on hotels booked direct*» / «8x points on all purchases
    # through Chase Travel, including The Edit℠*»: the qualifiers are stored with their words, not dropped.
    c = run_official("chase", "chase-sapphire-reserve", "sapphire-reserve-2026-10-14.rendered.html")
    assert conds(c, "airline") == {"booked_direct": "on flights booked direct*"}
    assert conds(c, "hotel") == {"booked_direct": "on hotels booked direct*"}
    assert conds(c, "travel") == {"portal_only": "on all purchases through Chase Travel"}
    assert conds(c, "dining") == {}  # «3x points on dining worldwide»


def test_a_surpass_us_only_and_partner_qualifiers() -> None:
    # «6X Points on Dining At U.S. restaurants» / «6X Points on Groceries At U.S. supermarkets» / «6X Points on Gas At
    # U.S. gas stations» / «4X Points on U.S. Online Retail Purchases» / «12X Points on Hotels & Resorts For eligible
    # purchases made directly with hotels and resorts within the Hilton portfolio»
    c = run_official("american_express", "hilton-honors-surpass", "hilton-surpass-2026-10-14.html")
    assert conds(c, "dining") == {"us_only": "U.S. restaurants"}
    assert conds(c, "groceries") == {"us_only": "U.S. supermarkets"}
    assert conds(c, "gas") == {"us_only": "U.S. gas stations"}
    assert conds(c, "online_shopping") == {"us_only": "U.S. Online Retail Purchases"}
    h = conds(c, "hotel")
    assert (
        set(h) == {"booked_direct", "partner_only"}
        and "made directly with hotels and resorts" in h["booked_direct"]
    )
    [hv] = [r.value for r in c.reward_rates if r.value and r.value.category == "hotel"]
    assert next(x.detail for x in hv.conditions if x.kind == "partner_only") == "Hilton"


def test_a_savor_good_credit_grocery_excludes_superstores() -> None:
    # «Earn unlimited 3% cash back at grocery stores (excluding superstores like Walmart® and Target®), ...»
    c = run_official("capital_one", "savor-good-credit", "savor-good-credit-2026-10-14.html")
    assert "excluding superstores like Walmart® and Target®" in conds(c, "groceries")["excludes_superstores"]


def test_a_qualifier_scope_in_lists() -> None:
    # "U.S." limits only the category it precedes; "booked directly" only the item it follows; "worldwide" and
    # "including ... in the U.S." do not make the main category U.S.-only; the portal's "booked directly in the Travel
    # Center" is portal-only, not booked-direct.
    def c_of(t: str) -> dict[str, set[str]]:
        rr = parse_reward_statement(t)
        assert rr is not None
        return {k: {x[0] for x in v} for k, v in rr.conditions.items()}

    assert c_of("3% cash back at U.S. gas stations and on transit") == {"gas": {"us_only"}}
    assert c_of("Earn 5X points on flights booked directly, car rental agencies, on dining") == {
        "airline": {"booked_direct"}
    }
    assert c_of("2X Miles at restaurants, including takeout and delivery in the U.S.") == {}
    assert c_of(
        "Earn 5% cash back on prepaid hotels and car rentals booked directly in the Travel Center."
    ) == {"travel": {"portal_only"}}


def test_a_recommender_counts_restricted_rates_only_with_opt_in() -> None:
    # A booked-direct airline/hotel rate never counts for generic travel spend; a portal-only travel rate counts only
    # when the user says they book through the portal.
    portal = RateView(
        category="travel",
        rate=Decimal("5"),
        rate_unit="x",
        portal_only=True,
        conditions=[RateConditionView(kind="portal_only", text="booked through Example Bank Travel")],
    )
    p = card(rates=[portal, rate("travel", "2", "x"), rate("other", "1", "x")], reward_currency="points")
    sp = MonthlySpend(travel=100)
    off, _, _, notes = cards.annual_rewards(p, req(monthly_spend=sp), Decimal("1"), NOW)
    on, _, _, _ = cards.annual_rewards(p, req(monthly_spend=sp, opt_in_portal=True), Decimal("1"), NOW)
    assert (off, on) == (2400, 6000) and any("Portal-only" in n for n in notes)
    direct = RateView(
        category="travel",
        rate=Decimal("4"),
        rate_unit="x",
        conditions=[RateConditionView(kind="booked_direct", text="on flights booked direct")],
    )
    p2 = card(rates=[direct, rate("other", "1", "x")], reward_currency="points")
    assert cards.annual_rewards(p2, req(monthly_spend=sp), Decimal("1"), NOW)[0] == 1200
    assert (
        cards.annual_rewards(p2, req(monthly_spend=sp, opt_in_booked_direct=True), Decimal("1"), NOW)[0]
        == 4800
    )
    us = RateView(
        category="dining",
        rate=Decimal("6"),
        rate_unit="x",
        conditions=[RateConditionView(kind="us_only", text="U.S. restaurants")],
    )
    v, _, _, notes = cards.annual_rewards(
        card(rates=[us, rate("other", "1", "x")], reward_currency="points"),
        req(monthly_spend=MonthlySpend(dining=100)),
        Decimal("1"),
        NOW,
    )
    assert v == 7200 and "Dining: U.S. purchases only." in notes


def test_b_ihg_hotel_tile_and_time_bound_program_rates() -> None:
    # «Up to 17X total points at IHG® Hotels and Resorts» / «That's 5X points with this card.*», and the
    # rewards-program terms on the page: «You’ll earn 3 points for each $1 spent on purchases that post to your account
    # through December 31, 2026 in the following rewards categories: utilities; internet, cable, and phone services;
    # select streaming services.» Both were missing; the card was shown as complete.
    c = run_official("chase", "ihg-one-rewards", "ihg-one-rewards-2026-10-14.rendered.html")
    by = {(r.value.category, r.value.rate): r.value for r in c.reward_rates if r.value}
    hotel = by[("hotel", Decimal("5"))]
    assert [(x.kind, x.detail) for x in hotel.conditions] == [("partner_only", "IHG")]
    assert "That's 5X points with this card" in hotel.text
    for cat in ("utilities", "telecom", "streaming"):
        assert by[(cat, Decimal("3"))].ends_on == date(2026, 12, 31)
    assert by[("other", Decimal("2"))].ends_on is None  # «2X after» is the base rate
    assert c.fields["earn_rates_complete"].value is True


def test_b_program_terms_rate_without_a_category_fails_completeness() -> None:
    # «You'll earn 2.5% Cash Back rewards total for each $1 spent on every purchase totaling $5,000 or more»: a real
    # earn rate with no category to hold it, so the card is not complete (it was before only for another reason).
    c = run_official("chase", "ink-business-premier", "ink-premier-summary-block.rendered.html")
    assert c.fields["earn_rates_complete"].null_reason is NullReason.ambiguous
    assert any(n.startswith("rewards-program terms not represented: You'll earn 2.5%") for n in c.notes)


def test_b_program_statements_split_and_clean() -> None:
    text = (
        "Earning in the Rewards Program: You'll earn points on purchases of products and services, minus returns. "
        "1 point: You'll earn 1 point for each $1 spent. 5 points (\"5X points\"): You'll earn 5 points total for each "
        "$1 spent (4 additional points on top of the 1 point per $1 earned on each purchase) on office supply stores."
    )
    got = [p for _, p in X.program_statements(text)]
    assert got == [
        "You'll earn 1 point for each $1 spent on all other purchases.",
        "You'll earn 5 points for each $1 spent on office supply stores.",
    ]


def test_b_program_paragraph_is_not_an_earn_statement_and_merchant_promo_kept() -> None:
    # Instacart's rewards-program terms (revised 2026-10-14) say «... (4% additional Cash Back rewards on up to $6,000
    # spent annually on top of the 1% Cash Back rewards earned on all qualifying Instacart purchases). After $6,000 ...
    # you go back to earning 1% Cash Back rewards for each $1 spent, with no maximum.» Read as page earn statements,
    # those fragments made a 1% partner rate that replaced the 5% one. The terms are read clause by clause instead.
    c = run_official("chase", "instacart-mastercard", "instacart-2026-10-14-1939.rendered.html")
    by = {r.value.category: r.value for r in c.reward_rates if r.value}
    assert (by["partner"].rate, by["partner"].cap_cents) == (Decimal("5"), 600000)
    assert c.fields["earn_rates_complete"].value is True


def test_b_named_merchant_total_is_the_cards_rate_but_loyalty_totals_are_not() -> None:
    from bankrec.ingest.adapters.chase import _NOT_EARN

    assert _NOT_EARN.search("Earn 5% total cash back on Lyft rides") is None
    assert (
        _NOT_EARN.search("Plus, earn 10x total points on eligible Peloton equipment and accessory purchases")
        is None
    )
    assert _NOT_EARN.search("9x total miles on eligible United flights*") is not None
    assert _NOT_EARN.search("14X total points at hotels participating in Marriott Bonvoy") is not None


def test_chase_third_template_offer_and_fee() -> None:
    # Chase moved Sapphire Reserve for Business to a third page template during the round-2 re-run (2026-10-14 19:50):
    # «OUR BEST OFFER RETURNS» / «Earn 200,000 points» / «after you spend $30,000 on purchases in your first 6 months
    # from account opening.*» and «$795 annual fee†; Employee Cards at no additional cost*».
    c = run_official(
        "chase", "sapphire-reserve-for-business", "sapphire-reserve-business-third-template.rendered.html"
    )
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (200000, "points", 3000000)
    assert window(o) == (6, "months", None)
    assert c.value("annual_fee_cents") == 79500
    assert c.fields["earn_rates_complete"].value is True


def test_time_bound_rate_referring_back_to_the_previous_categories() -> None:
    # «2X points per $1 spent at grocery stores. Through December 31, 2026, these purchases will earn 3X points per $1
    # spent.*»: 2X is the ongoing rate (it was stored as ending 2026-12-31) and the 3X promotion was missing.
    c = run_official("chase", "air-canada-aeroplan", "air-canada-aeroplan-2026-10-14.rendered.html")
    got = sorted(
        (r.value.category, r.value.rate, r.value.ends_on)
        for r in c.reward_rates
        if r.value and r.value.category in {"groceries", "dining"}
    )
    assert got == [
        ("dining", Decimal("2"), None),
        ("dining", Decimal("3"), date(2026, 12, 31)),
        ("groceries", Decimal("2"), None),
        ("groceries", Decimal("3"), date(2026, 12, 31)),
    ]


def test_united_tiers_after_pqp_lines() -> None:
    # «Earn up to 100,000 bonus miles + 2,000 Premier qualifying points (PQP)» / «Earn 90,000 bonus miles + 2,000 PQP
    # after you spend $5,000 ...» / «The 2,000 PQP are in addition to ...» / «Plus, earn 10,000 bonus miles after you
    # add an employee card ...»: tiered, not "up to 100,000 after $5,000".
    c = run_official("chase", "united-business", "united-business-2026-10-14.rendered.html")
    [o] = offers(c)
    assert o.amount_qualifier == "tiered" and [(t.amount, t.requirement_min_cents) for t in o.tiers] == [
        (90000, 500000),
        (10000, None),
    ]
    # «Earn 500 PQP after first purchase and 80,000 bonus miles after you spend $4,000 ...»
    c = run_official("chase", "united-quest", "united-quest-2026-10-14.rendered.html")
    [o] = offers(c)
    assert o.amount_qualifier == "tiered" and [(t.amount, t.requirement_min_cents) for t in o.tiers] == [
        (80000, 400000),
        (10000, None),
    ]


def test_annual_statement_credit_is_not_a_welcome_offer() -> None:
    # «Earn a $50 annual statement credit after $5,000 in purchases made through the Travel Center when you use your
    # card.» is a yearly benefit.
    c = run_official("us_bank", "business-shield-credit-card", "business-shield-2026-10-14.rendered.html")
    assert offers(c) == []


def test_merchant_promotions_keep_their_end_dates() -> None:
    # «5x on Peloton purchases» / «Earn 5x total points on eligible Peloton equipment and accessory purchases over $150
    # through 12/31/27.*» / «5x on Lyft rides» / «Earn 5x on Lyft rides through 9/30/27.*» (Sapphire Preferred,
    # round-1 fixture): two dated promotions, not one undated 5x.
    c = run_official(
        "chase", "chase-sapphire-preferred", "creditcards-rewards-credit-cards-sapphire-preferred.html"
    )
    got = sorted(r.value.ends_on for r in c.reward_rates if r.value and r.value.category == "merchant")
    assert got == [date(2027, 9, 30), date(2027, 12, 31)]


def test_flex_items_are_separate_lines() -> None:
    # Chase's summary blocks as spans in a flex column (Ink Business Preferred, 2026-10-14 20:19): the text read
    # «NEW CARDMEMBER OFFEREarn 100,000 bonus pointsafter you spend $8,000 ...» and the offer was not read.
    c = run_official("chase", "ink-business-preferred", "ink-preferred-flex-spans.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.requirement_min_cents) == (100000, 800000)
    assert c.value("annual_fee_cents") == 9500
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("17.99"),
        Decimal("26.99"),
    )
    t = parse_html(
        "<div class='flex flex-col'><span>NEW OFFER</span><span>Earn 5</span></div><p>a <span>b</span></p>"
    ).text
    assert t.split("\n") == ["NEW OFFER", "Earn 5", "a b"]
