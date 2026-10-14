"""Bank of America adapter tests on verbatim official pages (tests/fixtures/bank_of_america/RETRIEVED.txt, 2026-10-13).

Card content is inserted by the page script, so the fixtures are rendered captures; one static capture shows the
shell the server sends. Every expected value was read off the fixture's page text by hand.
"""

from decimal import Decimal

from bankrec.classify.classifier import classify, classify_retrieval
from bankrec.ingest.common.html import parse_html
from bankrec.model import PageType
from bankrec.registry.loader import load_registry
from bankrec.validation.rules import validate
from tests.adapters._helpers import FIX, rates, run_official

B = FIX / "bank_of_america"


def _offer(c):  # type: ignore[no-untyped-def]
    [o] = [o.value for o in c.offers if o.value]
    return o


def test_unlimited_cash_rewards() -> None:
    c = run_official(
        "bank_of_america",
        "unlimited-cash-back-credit-card",
        "credit-cards-products-unlimited-cash-back-credit-card.rendered.html",
    )
    assert c.parser_version == "bank_of_america/1.1.0"
    assert c.name == "Bank of America® Unlimited Cash Rewards Credit Card"
    assert c.value("annual_fee_cents") == 0
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("17.74"),
        Decimal("27.74"),
    )
    # "0% for 15 billing cycles — Applies to purchases, and to any balance transfers made within 60 days"
    assert (c.value("intro_purchase_apr_pct"), c.value("intro_purchase_apr_months")) == (Decimal("0"), 15)
    assert c.value("intro_bt_apr_months") == 15
    assert c.value("bt_fee_pct") == Decimal("5")  # the fee after the 3% intro fee ends
    assert c.value("foreign_tx_fee_pct") is None  # not stated on the page
    assert rates(c) == {"other": ("1.5pct", None)} and c.value("reward_currency") == "cashback"
    o = _offer(c)
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
        100000,
        90,
    )


def test_customized_cash_shared_quarterly_cap() -> None:
    c = run_official(
        "bank_of_america",
        "cash-back-credit-card",
        "credit-cards-products-cash-back-credit-card.rendered.html",
    )
    r = rates(c)
    # "Automatic 2% cash back at grocery stores and wholesale clubs" + "on the first $2,500 in combined purchases each
    # quarter in the choice category, and at grocery stores and wholesale clubs"
    assert r["groceries"] == r["wholesale_clubs"] == ("2pct", 250000)
    assert all(
        x.value.cap_period == "quarterly" and x.value.cap_combined
        for x in c.reward_rates
        if x.value and x.value.cap_cents
    )
    assert r["other"] == ("1pct", None)
    # The 3% (6% first-year) choice category depends on the cardholder's choice: not a fixed category, left out.
    assert set(r) == {"groceries", "wholesale_clubs", "other"}
    assert _offer(c).amount_max == 20000


def test_premium_rewards_points_and_online_bonus_points() -> None:
    c = run_official(
        "bank_of_america",
        "premium-rewards-credit-card",
        "credit-cards-products-premium-rewards-credit-card.rendered.html",
    )
    assert c.value("annual_fee_cents") == 9500 and c.value("foreign_tx_fee_pct") == Decimal("0")
    assert c.value("intro_purchase_apr_pct") is None  # "Introductory APR None"
    # "2 points ... on travel and dining purchases and unlimited 1.5 points ... on all other purchases": two rates.
    assert rates(c) == {"travel": ("2x", None), "dining": ("2x", None), "other": ("1.5x", None)}
    o = _offer(c)
    # "60,000 online bonus points — a $600 value — after you make at least $4,000": points, never $600 cash.
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (60000, "points", 400000)


def test_travel_rewards_everyday_purchases_is_base() -> None:
    c = run_official(
        "bank_of_america",
        "travel-rewards-credit-card",
        "credit-cards-products-travel-rewards-credit-card.rendered.html",
    )
    assert c.value("base_rate") == Decimal("1.5") and c.value("reward_currency") == "points"
    assert c.value("foreign_tx_fee_pct") == Decimal("0")  # "No annual fee and no foreign transaction fees"
    assert _offer(c).amount_max == 25000


def test_air_france_co_brand() -> None:
    c = run_official(
        "bank_of_america",
        "air-france-credit-card",
        "credit-cards-products-air-france-credit-card.rendered.html",
    )
    assert c.value("is_co_branded") is True and c.value("co_brand_partner") == "Air France"
    assert c.value("network") == "Visa" and c.value("annual_fee_cents") == 8900
    o = _offer(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (50000, "miles", 200000)


def test_secured_deposit() -> None:
    c = run_official(
        "bank_of_america", "secured-credit-card", "credit-cards-products-secured-credit-card.rendered.html"
    )
    assert c.value("is_secured") is True
    assert (
        c.value("secured_min_deposit_cents") == 20000
    )  # "A minimum security deposit of $200 (maximum of $5,000)"
    assert c.value("purchase_apr_min_pct") == Decimal("26.24")


def test_static_shell_yields_no_values_and_is_not_valid() -> None:
    """The server-sent HTML has only navigation and "temporarily unavailable": nothing may be read from it."""
    reg = load_registry(require_sources=False)
    bank = reg.bank("bank_of_america")
    html = (B / "static-unlimited-cash-back-credit-card.html").read_text()
    doc = parse_html(html)
    url = "https://www.bankofamerica.com/credit-cards/products/unlimited-cash-back-credit-card/"
    assert (
        classify_retrieval(200, url, "text/html", doc, bank.official_domains, bank.boilerplate_phrases)
        is None
    )
    c = run_official(
        "bank_of_america", "unlimited-cash-back-credit-card", "static-unlimited-cash-back-credit-card.html"
    )
    assert c.value("annual_fee_cents") is None and c.value("foreign_tx_fee_pct") is None and not c.offers
    v = validate(c, doc.text, bank.official_domains)
    assert v.status != "valid" and "annual_fee_cents" in v.missing_required


def test_boilerplate_does_not_make_the_rendered_page_blocked() -> None:
    reg = load_registry(require_sources=False)
    bank = reg.bank("bank_of_america")
    doc = parse_html((B / "credit-cards-products-unlimited-cash-back-credit-card.rendered.html").read_text())
    assert "temporarily unavailable" in doc.text  # visible on the real page
    url = "https://www.bankofamerica.com/credit-cards/products/unlimited-cash-back-credit-card/"
    assert (
        classify_retrieval(200, url, "text/html", doc, bank.official_domains, bank.boilerplate_phrases)
        is None
    )
    cl = classify(
        url,
        doc,
        "Bank of America® Unlimited Cash Rewards Credit Card",
        source_kind="product_detail",
        boilerplate=bank.boilerplate_phrases,
    )
    assert cl.page_type is PageType.official_product_detail


def test_terms_page_schumer_box() -> None:
    """The rendered "Terms and Conditions for ..." page (its campaignid/productoffercode/locale kept)."""
    from datetime import UTC, datetime

    from bankrec.ingest.adapters import get_adapter
    from bankrec.ingest.adapters.base import ClassifiedPage
    from bankrec.registry.schema import SourceEntry

    reg = load_registry(require_sources=False)
    bank = reg.bank("bank_of_america")
    url = "https://www.bankofamerica.com/credit-cards/terms-and-conditions/?campaignid=4082058&productoffercode=6E&locale=en_US"
    doc = parse_html((B / "terms-unlimited-cash-back.rendered.html").read_text())
    src = SourceEntry(
        bank_id="bank_of_america",
        slug="unlimited-cash-back-credit-card-terms",
        product_type="credit_card",
        source_url=url,
        source_kind="terms_page",
        parser_name="bank_of_america",
        expected_entity="Bank of America® Unlimited Cash Rewards Credit Card",
    )
    cl = classify(
        url, doc, src.expected_entity, source_kind="terms_page", boilerplate=bank.boilerplate_phrases
    )
    assert cl.page_type is PageType.terms_page
    page = ClassifiedPage(src, bank, url, cl.page_type, datetime.now(UTC), doc.text, doc)
    c = get_adapter("bank_of_america").extract(page)[0]
    assert c.name == "Bank of America® Unlimited Cash Rewards"  # same canonical key as the product page
    assert c.value("annual_fee_cents") == 0  # "Annual Fee / None"
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("17.74"),
        Decimal("27.74"),
    )
    assert c.value("foreign_tx_fee_pct") == Decimal(
        "3"
    )  # "3% of the U.S. dollar amount of each transaction ..."
    assert c.value("bt_fee_pct") == Decimal("5")
    assert c.reward_rates == [] and not c.offers  # rewards and offers come from the product page only
