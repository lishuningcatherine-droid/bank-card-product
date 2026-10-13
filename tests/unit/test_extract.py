from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters import get_adapter
from bankrec.ingest.adapters.base import ClassifiedPage
from bankrec.ingest.common.html import parse_html
from bankrec.model import ExtractionContext, NullReason, PageType, ProductType, Sourced
from bankrec.registry.loader import load_registry

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "example_bank"


def extract(rel: str, slug: str, adapter: str = "example_bank") -> ProductCandidate:
    reg = load_registry(include_test_only=True)
    src = next(s for s in reg.sources if s.slug == slug)
    doc = parse_html((FIX / rel).read_text())
    page = ClassifiedPage(
        source=src,
        bank=reg.bank("example_bank"),
        url=str(src.source_url),
        page_type=PageType.official_product_detail,
        retrieved_at=datetime.now(UTC),
        text=doc.text,
        doc=doc,
    )
    return get_adapter(adapter).extract(page)[0]


def test_provenance_guard_refuses_values_not_in_snapshot() -> None:
    ctx = ExtractionContext("Annual Fee $95")
    assert ctx.field(9500, "Annual Fee $95").present
    refused = ctx.field(9900, "Annual Fee $99", name="annual_fee")
    assert not refused.present and refused.null_reason is NullReason.not_found
    assert ctx.refused == [("annual_fee", "Annual Fee $99")]
    assert not ctx.field(1, None).present


def test_sourced_requires_reason_or_span() -> None:
    import pytest

    with pytest.raises(ValueError):
        Sourced(value=None)
    with pytest.raises(ValueError):
        Sourced(value=5)


def test_card_values() -> None:
    c = extract("card_everyday_cash.html", "everyday-cash")
    assert c.product_type is ProductType.credit_card
    v = c.value
    assert v("official_name") == "Example Bank Everyday Cash Card"
    assert v("annual_fee_cents") == 0 and v("foreign_tx_fee_pct") == Decimal("3")
    assert (v("purchase_apr_min_pct"), v("purchase_apr_max_pct")) == (Decimal("19.24"), Decimal("28.24"))
    assert (v("intro_purchase_apr_pct"), v("intro_purchase_apr_months")) == (Decimal("0"), 15)
    assert (v("bt_fee_pct"), v("bt_fee_min_cents")) == (Decimal("5"), 500)
    assert (v("au_fee_cents"), v("au_free_count")) == (0, 4)
    assert (
        v("network") == "Visa"
        and v("segment") == "consumer"
        and v("credit_profile_guidance") == "Good to Excellent"
    )
    cats = {(r.value.category, r.value.rate) for r in c.reward_rates if r.value}
    assert cats == {("dining", Decimal("3")), ("groceries", Decimal("2")), ("other", Decimal("1"))}
    o = c.offers[0].value
    assert (
        o is not None
        and o.amount_qualifier == "exact"
        and o.amount_max == 20000
        and o.requirement_min_cents == 50000
    )
    # every present field has quoted evidence found in the page
    for f in c.fields.values():
        if f.present:
            assert f.span_text and f.span_start is not None


def test_scheduled_fee_and_credits_and_portal() -> None:
    c = extract("card_voyager_rewards.html", "voyager-rewards")
    assert c.value("annual_fee_cents") == 9500 and c.value("intro_annual_fee_cents") == 0
    assert (
        c.value("future_annual_fee_cents") == 12500
        and str(c.value("annual_fee_effective_date")) == "2027-03-01"
    )
    credits = [b.value for b in c.benefits if b.value and b.value.monetizable]
    assert len(credits) == 1 and credits[0].amount_cents == 5000 and credits[0].period == "annual"
    assert any(r.value and r.value.portal_only for r in c.reward_rates)
    assert c.offers[0].value is not None and c.offers[0].value.amount_qualifier == "up_to"


def test_flags() -> None:
    assert extract("card_business_cash.html", "business-cash").value("segment") == "business"
    s = extract("card_secured.html", "secured")
    assert s.value("is_secured") is True and s.value("secured_min_deposit_cents") == 20000
    assert extract("card_student_cash.html", "student-cash").value("is_student") is True
    co = extract("card_example_air_miles.html", "example-air-miles")
    assert co.value("is_co_branded") is True and co.value("co_brand_partner") == "Example Air"
    assert co.value("reward_currency") == "miles"


def test_bare_dollar_apr_is_requires_render() -> None:
    """U.S. Bank pre-survey pattern: APR shows as a bare '$' in static HTML."""
    c = extract("pages/card_bare_dollar_apr.html", "secured")
    f = c.fields["purchase_apr_min_pct"]
    assert not f.present and f.null_reason is NullReason.requires_render


def test_static_nan_apy_is_requires_render() -> None:
    """Capital One pre-survey pattern: APY renders client-side and shows NaN statically."""
    c = extract("pages/savings_static_nan.html", "high-yield")
    assert c.fields["apy_pct"].null_reason is NullReason.requires_render


def test_checking_waivers_tiers_states() -> None:
    c = extract("checking_everyday_checking.html", "everyday-checking")
    assert c.value("monthly_fee_cents") == 1200 and c.value("min_opening_deposit_cents") == 2500
    kinds = {(w.kind, w.amount_cents, w.age_max) for w in c.value("fee_waivers")}
    assert kinds == {
        ("electronic_deposit_total", 50000, None),
        ("min_daily_balance", 150000, None),
        ("age", None, 23),
    }
    assert c.value("eligible_states") == ["NY", "NJ", "CT", "PA"]
    o = c.offers[0].value
    assert o is not None and [t.amount for t in o.tiers] == [30000, 50000]
    assert o.requirement_type == "direct_deposit_total" and o.qualification_window_days == 90


def test_savings_tiers_and_bonus() -> None:
    t = extract("savings_tiered.html", "tiered")
    tiers = t.value("apy_tiers")
    assert [str(x.apy_pct) for x in tiers] == ["0.50", "2.00", "3.25"]
    assert t.fields["apy_pct"].null_reason is NullReason.not_applicable
    h = extract("savings_high_yield.html", "high-yield")
    assert h.value("apy_pct") == Decimal("4.00") and h.value("max_withdrawals_per_month") == 6
    o = h.offers[0].value
    assert o is not None and o.requirement_type == "new_money_deposit" and o.holding_period_days == 90


def test_struck_out_and_screen_reader_text_is_not_visible() -> None:
    from bankrec.ingest.common.html import parse_html

    doc = parse_html(
        '<h1>Example Bank Card<sup>SM</sup></h1><p>Earn a <span class="strikeThrough">$200'
        '<span class="visually-hidden">Strike through</span></span> $250 bonus</p><p><del>$95</del> $0</p>'
    )
    assert doc.h1 == ["Example Bank Card℠"]
    assert "Earn a $250 bonus" in doc.text and "$200" not in doc.text and "$95" not in doc.text


def test_scoped_doc_excludes_navigation() -> None:
    from bankrec.ingest.common.html import parse_html, scoped

    doc = parse_html(
        "<nav>No Annual Fee (15)</nav><main><div class='browse'>No Foreign Transaction Fees</div>"
        "<h1>Example Bank Card</h1><p>Annual fee: $95</p></main>"
    )
    sub = scoped(doc, "main", ".browse")
    assert "No Annual Fee" not in sub.text and "Foreign" not in sub.text and "Annual fee: $95" in sub.text
