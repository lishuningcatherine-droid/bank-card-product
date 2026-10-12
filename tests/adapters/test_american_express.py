"""American Express adapter (brief §6.7). Verbatim fixtures pending; logic tested on synthetic Example Bank pages."""

from pathlib import Path

import pytest

from bankrec.ingest.adapters.american_express import OFFER_ABSENT, OFFER_NOTE
from tests.adapters._helpers import FIX, run_adapter, verbatim_fixtures

PENDING = (
    "pending: no verbatim official American Express fixture (ENV_NETWORK_BLOCKED; see docs/REACHABILITY.md)"
)
E = FIX / "example_bank"


@pytest.mark.pending_fixture
@pytest.mark.skipif(not verbatim_fixtures("american_express"), reason=PENDING)
def test_verbatim_official_fixtures() -> None:  # pragma: no cover
    for f in verbatim_fixtures("american_express"):
        raise AssertionError(f"write value assertions for {f.name} before enabling sources")


def test_offer_found_gets_variability_note() -> None:
    c = run_adapter("american_express", E / "card_voyager_rewards.html", "voyager-rewards")
    o = c.offers[0].value
    assert o is not None and o.audience == "public" and o.note == OFFER_NOTE and o.verbatim_text


def test_offer_absent_statically_creates_no_offer(tmp_path: Path) -> None:
    html = (E / "card_voyager_rewards.html").read_text()
    start, end = (
        html.index('<section class="offer">'),
        html.index("</section>", html.index('<section class="offer">')),
    )
    page = tmp_path / "no_offer.html"
    page.write_text(html[:start] + html[end + len("</section>") :])
    c = run_adapter("american_express", page, "voyager-rewards")
    assert c.offers == [] and c.offer_absent_note == OFFER_ABSENT


def test_annual_fee_from_faq_answer(tmp_path: Path) -> None:
    html = (E / "card_voyager_rewards.html").read_text()
    html = html.replace(
        "<tr><th>Annual Fee</th><td>$0 intro annual fee for the first year, then $95</td></tr>", ""
    )
    html = html.replace(
        "</main>",
        "<h2>FAQ</h2><h3>What is the annual fee for the Example Bank Voyager Rewards Card?"
        "</h3><p>It is $95 per year.</p></main>",
    )
    page = tmp_path / "faq_fee.html"
    page.write_text(html)
    c = run_adapter("american_express", page, "voyager-rewards")
    assert c.value("annual_fee_cents") == 9500
    assert c.fields["annual_fee_cents"].span_text == "It is $95 per year."
    assert "annual fee taken from FAQ answer" in c.notes
