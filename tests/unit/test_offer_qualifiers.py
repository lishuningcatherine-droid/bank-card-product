"""amount_qualifier parsing (brief §5.4, DESIGN §22.5) on synthetic Example Bank fixtures."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bankrec.ingest.common.html import parse_html
from bankrec.parsers.offers import Qualifier, parse_offer_block

OFF = Path(__file__).resolve().parents[1] / "fixtures" / "example_bank" / "offers"


def _block(name: str) -> tuple[str, str]:
    doc = parse_html((OFF / f"{name}.html").read_text())
    head = " ".join(doc.node_text(n) for n in doc.select(".offer .offer-headline"))
    foot = " ".join(doc.node_text(n) for n in doc.select(".offer .footnote"))
    return head, foot


@pytest.mark.parametrize(
    ("fixture", "q", "lo", "hi", "unit"),
    [
        ("exact_points", Qualifier.exact, 60000, 60000, "points"),
        ("up_to_points", Qualifier.up_to, None, 80000, "points"),
        ("as_high_as_cash", Qualifier.up_to, None, 30000, "cents"),
        ("may_be_eligible", Qualifier.up_to, None, 75000, "miles"),
        ("footnote_may_vary", Qualifier.up_to, None, 60000, "points"),
        ("starting_at", Qualifier.starting_at, 50000, None, "points"),
    ],
)
def test_qualifier_fixtures(fixture: str, q: Qualifier, lo: int | None, hi: int | None, unit: str) -> None:
    head, foot = _block(fixture)
    p = parse_offer_block(head, foot)
    assert p is not None
    assert (p.qualifier, p.amount_min, p.amount_max, p.reward_unit) == (q, lo, hi, unit)


def test_exact_requirement_and_window() -> None:
    p = parse_offer_block(*_block("exact_points"))
    assert p is not None
    assert (p.requirement_type, p.requirement_min_cents, p.requirement_max_cents) == ("spend", 400000, 400000)
    assert p.window is not None and p.window.months == 3


def test_negatives_do_not_set_qualifier() -> None:
    """'on up to $1,500' (a cap), 'up to 5% cash back' (a rate) and 'spend at least' (a requirement)."""
    p = parse_offer_block(*_block("negatives"))
    assert p is not None
    assert p.qualifier is Qualifier.exact and p.amount_min == p.amount_max == 20000
    assert p.requirement_min_cents == 100000


def test_requirement_may_vary() -> None:
    p = parse_offer_block(
        "Earn 60,000 points after you spend $4,000 in 3 months. Spending requirements may vary."
    )
    assert p is not None and p.requirement_qualifier is Qualifier.up_to and p.requirement_max_cents == 400000
    assert p.requirement_min_cents is None


def test_direct_deposit_and_new_money() -> None:
    p = parse_offer_block("Get $300 when you set up direct deposits totaling $5,000 or more within 90 days.")
    assert (
        p is not None and p.requirement_type == "direct_deposit_total" and p.requirement_min_cents == 500000
    )
    n = parse_offer_block(
        "Earn a $200 bonus when you deposit $15,000 in new money within 30 days and maintain that "
        "balance for 90 days."
    )
    assert n is not None and n.requirement_type == "new_money_deposit" and n.holding is not None
    assert n.holding.days == 90 and n.amount_max == 20000


PHRASES = [
    "up to",
    "as high as",
    "earn up to",
    "you may be eligible for",
    "Earn up to",
    "UP TO",
    "As High As",
]


@given(
    st.sampled_from(PHRASES),
    st.integers(min_value=1000, max_value=200000),
    st.text(alphabet=" \n\t", max_size=5),
    st.text(alphabet="abcdefg ", max_size=20),
)
def test_variability_phrase_never_yields_exact(phrase: str, n: int, ws: str, noise: str) -> None:
    p = parse_offer_block(f"{noise} {phrase}{ws} {n:,} bonus points after you spend $3,000 in 3 months.")
    assert p is not None
    assert p.qualifier is Qualifier.up_to and p.amount_max == n and p.amount_min is None


@given(st.sampled_from(["*Offer may vary.", "Offers vary by applicant.", "The offer may vary."]))
def test_footnote_variability_is_up_to(foot: str) -> None:
    p = parse_offer_block("Earn 40,000 points after you spend $2,000 in 3 months.*", foot)
    assert p is not None and p.qualifier is Qualifier.up_to


def test_spending_and_your_first_months() -> None:
    po = parse_offer_block(
        "Earn 45,000 bonus points after spending $1,000 on eligible purchases in your first 3 months"
    )
    assert po is not None and po.requirement_min_cents == 100000 and po.window is not None
    assert po.window.months == 3


def test_avios_are_points() -> None:
    po = parse_offer_block("Earn 75,000 Avios after you spend $5,000 on purchases within the first 3 months")
    assert po is not None and (po.amount_max, po.reward_unit) == (75000, "points")
