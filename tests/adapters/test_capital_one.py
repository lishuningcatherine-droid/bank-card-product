"""Capital One adapter tests on verbatim official pages (tests/fixtures/capital_one/RETRIEVED.txt, 2026-10-13).

Every expected value below was read off the fixture's page text by hand.
"""

from decimal import Decimal

from bankrec.classify.classifier import classify
from bankrec.ingest.common.html import parse_html
from bankrec.model import NullReason, PageType
from bankrec.registry.loader import load_registry
from tests.adapters._helpers import FIX, rates, run_adapter, run_official

C = FIX / "capital_one"


def test_venture_x_showcase_pairs() -> None:
    c = run_official("capital_one", "venture-x", "www-credit-cards-venture-x.html")
    assert c.parser_version == "capital_one/1.0.0"
    assert c.name == "Venture X"
    assert c.value("annual_fee_cents") == 39500
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("19.74"),
        Decimal("28.74"),
    )
    assert c.value("credit_profile_guidance") == "Excellent"  # issuer-published "Credit Level"
    assert c.value("foreign_tx_fee_pct") == Decimal("0")
    assert c.value("reward_currency") == "miles" and c.value("base_rate") == Decimal("2")
    r = rates(c)
    assert r["other"] == ("2x", None)
    # 10X / 5X are "booked through Capital One Travel": portal-only, never applied to general spend.
    assert all(x.value.portal_only for x in c.reward_rates if x.value and x.value.category != "other")
    # The static page states no welcome offer (only a referral bonus, which is not one).
    assert not [o for o in c.offers if o.value]


def test_venture_name_from_eyebrow_and_static_offer() -> None:
    c = run_official("capital_one", "venture", "www-credit-cards-venture.html")
    # The h1 is a promotion ("Enjoy a $300 stays credit, plus earn 75K bonus miles"); the name is the eyebrow line.
    assert c.name == "Venture Rewards from Capital One"
    assert c.value("annual_fee_cents") == 9500
    assert c.value("foreign_tx_fee_pct") == Decimal("0")
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_qualifier, o.amount_max, o.reward_unit) == ("exact", 75000, "miles")
    assert (o.requirement_min_cents, (o.qualification_window_count, o.qualification_window_unit)) == (
        400000,
        (3, "months"),
    )


def test_venture_classifies_as_product_with_heading_selector() -> None:
    reg = load_registry(require_sources=False)
    bank = reg.bank("capital_one")
    doc = parse_html((C / "www-credit-cards-venture.html").read_text())
    url = "https://www.capitalone.com/credit-cards/venture/"
    name = "Venture Rewards from Capital One"
    # Without the bank's heading selector the promotional h1 hides the product heading: not a product page.
    assert (
        classify(url, doc, name, source_kind="product_detail").page_type
        is not PageType.official_product_detail
    )
    cl = classify(
        url, doc, name, source_kind="product_detail", heading_selectors=bank.product_heading_selectors
    )
    assert cl.page_type is PageType.official_product_detail


def test_savor_intro_apr_and_multi_category_rate() -> None:
    c = run_official("capital_one", "savor", "www-credit-cards-savor.html")
    assert c.value("annual_fee_cents") == 0  # showcase headline "$0 annual fee"
    assert c.value("intro_purchase_apr_pct") == Decimal("0") and c.value("intro_purchase_apr_months") == 12
    assert c.value("intro_bt_apr_months") == 12
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.74"),
        Decimal("28.74"),
    )
    r = rates(c)
    assert r["groceries"] == r["dining"] == r["entertainment"] == r["streaming"] == ("3pct", None)
    assert r["other"] == ("1pct", None)
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (20000, "cents", 50000)


def test_platinum_secured_deposit_and_no_rewards() -> None:
    c = run_official("capital_one", "platinum-secured", "www-credit-cards-platinum-secured.html")
    assert c.value("is_secured") is True
    assert c.value("secured_min_deposit_cents") == 4900  # "$49, $99 or $200 minimum refundable deposit"
    assert c.value("purchase_apr_min_pct") == c.value("purchase_apr_max_pct") == Decimal("29.24")
    assert c.reward_rates == [] and c.value("reward_currency") is None


def test_spark_cash_business_segment_and_intro_fee() -> None:
    c = run_official("capital_one", "spark-cash", "www-small-business-credit-cards-spark-cash.html")
    assert c.value("segment") == "business"  # /small-business/ page; the name "Spark Cash" does not say so
    # "Enjoy a $0 annual fee for the first year, and then $95 after that."
    assert (c.value("intro_annual_fee_cents"), c.value("annual_fee_cents")) == (0, 9500)
    assert c.value("purchase_apr_min_pct") == Decimal("24.74")
    assert c.value("base_rate") == Decimal("2") and c.value("reward_currency") == "cashback"
    [o] = [o.value for o in c.offers if o.value]
    assert (
        o.amount_max,
        o.reward_unit,
        o.requirement_min_cents,
        (o.qualification_window_count, o.qualification_window_unit),
    ) == (
        100000,
        "cents",
        1000000,
        (3, "months"),
    )


def test_logic_on_synthetic_placeholders() -> None:
    # Capital One's savings APY is client-rendered; a NaN placeholder must become missing (requires_render).
    s = run_adapter("capital_one", FIX / "example_bank" / "pages" / "savings_static_nan.html", "high-yield")
    assert s.fields["apy_pct"].null_reason is NullReason.requires_render
