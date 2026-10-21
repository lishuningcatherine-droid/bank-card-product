"""Capture quality gate (DESIGN §24.18), from stored captures: a degraded capture never proposes removing a value."""

from __future__ import annotations

from pathlib import Path

from bankrec.ingest.common.html import parse_html
from bankrec.ingest.quality import assess

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def page(rel: str) -> tuple[str, list[str]]:
    d = parse_html((FIX / rel).read_text(encoding="utf-8", errors="replace"))
    return d.text, d.h1


def test_amex_static_shell_is_degraded_against_the_published_rendered_capture() -> None:
    # Blue Cash Preferred's published values come from the rendered capture of 2026-10-13 (APR «19.74% to 28.74%»).
    # Since 10-13 20:25 the static captures have no APR at all; diffing them removed the APR (review item 78).
    q = assess(
        *page("american_express/blue-cash-preferred-shell-2026-10-14.html"),
        page("american_express/us-credit-cards-card-blue-cash-preferred.rendered.html"),
    )
    assert q.degraded and q.missing == ["apr"] and q.score < 1
    assert "apr" in q.detail


def test_disney_capture_passes_the_gate() -> None:
    # The Disney "removals" (items 293/294) were not a capture problem: the 2026-10-14 page has every section the
    # 2026-10-13 one had, at the same length, so the gate lets it through and the parser is what must be right.
    q = assess(
        *page("chase/disney-inspire-2026-10-14.rendered.html"),
        page("chase/disney-inspire-2026-10-13.rendered.html"),
    )
    assert not q.degraded and q.missing == [] and q.score == 1.0


def test_shrunk_text_is_degraded_and_no_baseline_passes() -> None:
    full = (
        "Example Bank Card\n3% cash back on dining\nAnnual fee $0\nAPR 19.99% - 29.99%\n" + "Details. " * 200
    )
    short = "Example Bank Card\n3% cash back on dining\nAnnual fee $0\nAPR 19.99% - 29.99%\n"
    assert assess(short, ["Example Bank Card"], (full, ["Example Bank Card"])).degraded
    assert not assess(short, ["Example Bank Card"], None).degraded


def test_rates_page_without_its_rate_table_is_degraded() -> None:
    # Chase Savings rates, ZIP 90024, 2026-10-21: the 06:12 capture still says "Annual Percentage Yield" but the
    # table ("0.01% 0.01%") did not load; it passed the gate and sent Chase Savings to review (item 403).
    good = (FIX / "chase/chase-savings-rates-90024-2026-10-21.txt").read_text(encoding="utf-8")
    bad = (FIX / "chase/chase-savings-rates-90024-2026-10-21-no-table.txt").read_text(encoding="utf-8")
    heading = ["Savings account interest rates"]
    q = assess(bad, heading, (good, heading))
    assert q.degraded and q.missing == ["apy"]
    assert not assess(good, heading, (good, heading)).degraded
