"""Deposit accounts (DESIGN §24.20-21), from the stored official pages of 2026-10-19 (ZIP 90024 where the page needs one).

Values were read off each snapshot by hand; the quoted words are the page's.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters import get_adapter
from bankrec.ingest.adapters.base import ClassifiedPage
from bankrec.ingest.common.html import parse_html
from bankrec.ingest.common.pdf import pdf_to_text
from bankrec.model import NullReason, PageType
from bankrec.registry.loader import load_registry
from tests.adapters._helpers import FIX


def run(bank: str, slug: str, fixture: str) -> list[ProductCandidate]:
    reg = load_registry(require_sources=False)
    src = next(s for s in reg.sources if s.bank_id == bank and s.slug == slug)
    path = FIX / bank / fixture
    kind = src.source_kind.value
    pt = {
        "terms_page": PageType.terms_page,
        "terms_pdf": PageType.pdf_terms,
        "offer_detail": PageType.official_offer_detail,
    }.get(
        kind,
        PageType.official_comparison_page
        if src.expected_entity == "multiple"
        else PageType.official_product_detail,
    )
    if fixture.endswith(".pdf"):
        doc, text = None, pdf_to_text(path.read_bytes())
    else:
        doc = parse_html(path.read_text(encoding="utf-8", errors="replace"))
        text = doc.text
    page = ClassifiedPage(
        source=src,
        bank=reg.bank(bank),
        url=str(src.source_url),
        page_type=pt,
        retrieved_at=datetime.now(UTC),
        text=text,
        doc=doc,
    )
    return get_adapter(reg.bank(bank).adapter).extract(page)


def one(bank: str, slug: str, fixture: str) -> ProductCandidate:
    [c] = run(bank, slug, fixture)
    return c


def waivers(c: ProductCandidate) -> list[tuple[str, int | None]]:
    return [(w.kind, w.amount_cents) for w in c.value("fee_waivers") or []]


def test_chase_total_checking_fee_waivers_and_no_opening_deposit_stated() -> None:
    # «$15 or $0 Monthly Service Fee» / «You can avoid the fee by doing ONE of the following each monthly statement
    # period: $500+ in qualifying electronic deposits -OR- $1,500+ balance at the beginning of each day -OR- $5,000+
    # average beginning day balance ... -OR- Link this account to a qualifying checking account»
    c = one("chase", "total-checking", "chase-total-checking-2026-10-19.html")
    assert c.name == "Chase Total Checking®" and c.value("monthly_fee_cents") == 1500
    assert waivers(c) == [
        ("electronic_deposit_total", 50000),
        ("min_daily_balance", 150000),
        ("min_avg_balance", 500000),
        ("linked_account", None),
    ]
    # no Chase page states a checking opening deposit: never inferred
    assert c.value("min_opening_deposit_cents") is None
    assert c.value("overdraft_summary").startswith("No overdraft fee if you're overdrawn by $50 or less")


def test_chase_checking_bonus_direct_deposit_requirement_and_end_date() -> None:
    # «Enjoy a $400 checking account bonus as a new Chase checking customer, when you open a Chase Total Checking®
    # account and make direct deposits totaling $1,000 or more within 90 days of offer enrollment.» «Offer expires
    # 01/27/2027.»
    c = one("chase", "total-checking-offer", "chase-total-checking-offer-2026-10-19.html")
    assert c.name == "Chase Total Checking®"
    [o] = [x.value for x in c.offers if x.value]
    assert (o.amount_qualifier, o.amount_max, o.reward_unit) == ("exact", 40000, "cents")
    assert (o.requirement_type, o.requirement_min_cents) == ("direct_deposit_total", 100000)
    assert (o.qualification_window_count, o.qualification_window_unit) == (90, "days")
    assert o.expiration_date == date(2027, 1, 27)


def test_chase_savings_rate_for_zip_90024() -> None:
    # after ZIP 90024: «Interest Rate» «Annual Percentage Yield» «0.01% 0.01%» … «90024 not your ZIP code?»
    c = one("chase", "chase-savings-rates", "chase-savings-rates-90024-2026-10-19.rendered.html")
    assert c.value("apy_pct") == Decimal("0.01")


def test_capital_one_360_checking_and_savings_apy_needs_the_blocked_script() -> None:
    c = one("capital_one", "360-checking", "360-checking-2026-10-19.html")
    assert (c.name, c.value("monthly_fee_cents"), c.value("min_opening_deposit_cents")) == (
        "360 Checking",
        0,
        0,
    )
    assert c.fields["fee_waivers"].null_reason is NullReason.not_applicable
    assert (
        c.fields["apy_tiers"].null_reason is NullReason.requires_render
    )  # «... an annual percentage yield (APY) of NaN»
    s = one("capital_one", "360-performance-savings", "360-performance-savings-2026-10-19.html")
    assert s.fields["apy_pct"].null_reason is NullReason.requires_render  # «NaN APY»: robots-blocked rate API


def test_bank_of_america_advantage_banking_one_record_per_account() -> None:
    # «Advantage Plus Banking» «$12 or $0» «$0 for each statement cycle that: You maintain a minimum daily balance of
    # $1,500 or more in your account OR You have at least 1 qualifying direct deposit of $250 or more ... OR An account
    # owner is enrolled in BofA Rewards™ ...»
    got = {
        c.name: c
        for c in run(
            "bank_of_america", "advantage-banking", "advantage-banking-90024-2026-10-19.rendered.html"
        )
    }
    assert set(got) == {
        "Advantage SafeBalance Banking",
        "Advantage Plus Banking",
        "Advantage Relationship Banking",
    }
    assert [got[n].value("monthly_fee_cents") for n in sorted(got)] == [1200, 2500, 495]
    assert waivers(got["Advantage Plus Banking"]) == [
        ("min_daily_balance", 150000),
        ("direct_deposit_total", 25000),
        ("other", None),
    ]
    assert waivers(got["Advantage Relationship Banking"]) == [("min_daily_balance", 2000000), ("other", None)]
    sb = got["Advantage SafeBalance Banking"].value("fee_waivers")
    assert [(w.kind, w.age_max) for w in sb][1] == ("age", 24)  # «An account owner is under age 25»


def test_bank_of_america_savings_fee_page_and_rate_sheet_tiers() -> None:
    s = one("bank_of_america", "advantage-savings", "advantage-savings-90024-2026-10-19.rendered.html")
    assert s.value("monthly_fee_cents") == 800  # «Monthly maintenance fee» «$8 or $0»
    assert waivers(s)[0] == ("min_daily_balance", 50000)
    r = one(
        "bank_of_america", "advantage-savings-rates", "advantage-savings-rates-los-angeles-2026-10-19.pdf"
    )
    tiers = r.value("apy_tiers")
    assert len(tiers) == 9 and {t.apy_pct for t in tiers} == {
        Decimal("0.04")
    }  # «Less than $5,000 0.04% 0.04%» …
    assert (tiers[0].min_balance_cents, tiers[0].max_balance_cents) == (0, 499999)
    assert (tiers[-1].min_balance_cents, tiers[-1].max_balance_cents) == (1000000000, None)
    # «Minimum to open: $1,000 CDs / $1,000 IRAs» is not the savings account's opening deposit
    assert r.value("min_opening_deposit_cents") is None


def test_us_bank_smartly_checking_waivers_and_savings_standard_rate() -> None:
    c = one("us_bank", "bank-smartly-checking", "bank-smartly-checking-2026-10-19.html")
    assert (c.value("monthly_fee_cents"), c.value("min_opening_deposit_cents")) == (1200, 2500)
    assert waivers(c)[:2] == [("min_avg_balance", 150000), ("direct_deposit_total", 150000)]
    r = one(
        "us_bank", "bank-smartly-savings-rates", "bank-smartly-savings-rates-90024-2026-10-19.rendered.html"
    )
    assert r.value("apy_pct") == Decimal("0.05")  # «Standard interest rate Standard APY» «0.05% 0.05%»


def test_amex_rewards_checking_and_high_yield_savings() -> None:
    c = one("american_express", "rewards-checking", "rewards-checking-2026-10-19.html")
    assert (c.value("monthly_fee_cents"), c.value("min_opening_deposit_cents")) == (0, 0)
    assert [t.apy_pct for t in c.value("apy_tiers")] == [Decimal("1.00")]  # «Earn a 1.00% APY»
    s = one("american_express", "high-yield-savings", "high-yield-savings-2026-10-19.rendered.html")
    assert s.value("apy_pct") == Decimal("3.20")  # «3.20% APY²»
