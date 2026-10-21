"""Home page public offer ranking (DESIGN §25.3) and offer audiences (§25.1). Synthetic Example Bank data only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from bankrec.ingest.common.extract import offer_audience
from bankrec.recommend.common import eligible_offers
from bankrec.recommend.models import OfferView, ProductView
from bankrec.recommend.public_offers import estimate, rank

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def offer(oid: str, **kw: Any) -> OfferView:
    base: dict[str, Any] = dict(
        id=oid,
        offer_type="card_welcome",
        reward_unit="points",
        amount_qualifier="exact",
        amount_min=60000,
        amount_max=60000,
        requirement_type="spend",
        requirement_qualifier="exact",
        requirement_min_cents=400000,
        requirement_max_cents=400000,
        offer_url="https://www.examplebank.example/cards/x",
        verified_at=NOW,
        last_confirmed_at=NOW,
        state="current",
        verbatim_text="Earn 60,000 bonus points after you spend $4,000",
    )
    base.update(kw)
    return OfferView(**base)


def card(name: str, offers: list[OfferView], label: str = "verified", **details: Any) -> ProductView:
    return ProductView(
        id=name,
        bank_id="example_bank",
        bank_name="Example Bank",
        product_type="credit_card",
        name=name,
        official_url="https://www.examplebank.example/cards/x",
        label=label,
        verified_at=NOW,
        last_checked_at=NOW,
        first_published_at=NOW,
        details={"annual_fee_cents": 0, **details},
        offers=offers,
    )


def test_estimate_values_points_at_default_and_subtracts_first_year_fee() -> None:
    p = card("A", [], annual_fee_cents=9500, intro_annual_fee_cents=0)
    e = estimate(p, offer("o"))
    assert not isinstance(e, str)
    assert (e.bonus_value_cents, e.first_year_fee_cents, e.net_first_year_cents) == (60000, 0, 60000)
    assert (e.group, e.value_basis) == ("points", "estimated, assumes 1.0¢/point")
    cash = estimate(
        card("B", [], annual_fee_cents=9500),
        offer("c", reward_unit="cents", amount_min=20000, amount_max=20000),
    )
    assert not isinstance(cash, str)
    assert (cash.group, cash.value_basis, cash.net_first_year_cents) == ("cash", "cash", 10500)


def test_up_to_and_restricted_currency_offers_are_not_valued() -> None:
    up = offer("u", amount_qualifier="up_to", amount_min=None, amount_max=80000)
    assert "up to" in str(estimate(card("A", []), up))
    assert "store currency" in str(estimate(card("D", [], reward_currency="restricted"), offer("r")))


def test_rank_only_public_current_offers_of_verified_products() -> None:
    products = [
        card("Big", [offer("big", amount_min=90000, amount_max=90000)], annual_fee_cents=55000),
        card("Free", [offer("free")]),
        card("Referral only", [offer("ref", audience="referral", amount_min=200000, amount_max=200000)]),
        card("Partial", [offer("partial", amount_min=200000, amount_max=200000)], label="partially_verified"),
        card("Stale", [offer("stale", state="stale", amount_min=200000, amount_max=200000)]),
        card("Up to", [offer("upto", amount_qualifier="up_to", amount_min=None, amount_max=100000)]),
    ]
    res = rank(products, "credit_card", "value", NOW, group="points")
    # value = bonus minus first-year fee: 60,000 points at 1.0¢ with no fee beats 90,000 points with a $550 fee
    assert [(r.rank, r.product.name) for r in res.items] == [(1, "Free"), (2, "Big")]
    assert [u.product.name for u in res.unranked] == ["Up to"]
    assert [r.product.name for r in rank(products, "credit_card", "bonus", NOW, group="points").items] == [
        "Big",
        "Free",
    ]
    assert any("1.0¢" in a for a in res.assumptions)


def test_same_product_offers_on_two_channels_rank_once_with_the_other_listed() -> None:
    page = offer("page", amount_min=60000, amount_max=60000)
    landing = offer(
        "landing", amount_min=75000, amount_max=75000, offer_url="https://www.examplebank.example/offers/x"
    )
    targeted = offer("mail", audience="targeted", amount_min=100000, amount_max=100000)
    [r] = rank([card("A", [page, landing, targeted])], "credit_card", "value", NOW, group="points").items
    assert r.offer.id == "landing"
    assert [o.id for o in r.other_public_offers] == ["page"]
    assert r.non_public_offers == 1


def test_ending_and_requirement_sorts() -> None:
    a = card(
        "A",
        [
            offer(
                "a",
                expiration_date=date(2027, 1, 1),
                requirement_min_cents=100000,
                requirement_max_cents=100000,
            )
        ],
    )
    b = card("B", [offer("b", expiration_date=date(2026, 12, 1))])
    c = card("C", [offer("c")])
    assert [r.product.name for r in rank([a, b, c], "credit_card", "ending", NOW, group="points").items] == [
        "B",
        "A",
        "C",
    ]
    assert rank([a, b, c], "credit_card", "requirement", NOW, group="points").items[0].product.name == "A"


def test_non_public_offers_are_never_recommended() -> None:
    p = card("A", [offer("pub"), offer("pre", audience="preapproved")])
    assert [o.id for o in eligible_offers(p)] == ["pub"]


def test_offer_audience_only_narrows() -> None:
    assert offer_audience("public", "Earn 60,000 bonus points after you spend $4,000") == ("public", None)
    assert offer_audience("public", "You've been pre-approved: earn 60,000 points")[0] == "preapproved"
    assert (
        offer_audience("public", "Referral offer: earn 50,000 points when referred by a friend")[0]
        == "referral"
    )
    assert offer_audience("public", "This offer is only available to selected recipients.")[0] == "targeted"
    # a registered audience is never made more public by the wording
    assert offer_audience("referral", "Earn 60,000 bonus points")[0] == "referral"


def test_cash_and_points_offers_are_never_ranked_together() -> None:
    cash = card("Cash", [offer("c", reward_unit="cents", amount_min=20000, amount_max=20000)])
    hotel = card(
        "Hotel", [offer("h", amount_min=190000, amount_max=190000)], reward_program="Example Hotel Points"
    )
    both = card("Both", [offer("bc", reward_unit="cents", amount_min=10000, amount_max=10000), offer("bp")])
    assert [r.product.name for r in rank([cash, hotel, both], "credit_card", "value", NOW).items] == [
        "Cash",
        "Both",
    ]
    pts = rank([cash, hotel, both], "credit_card", "value", NOW, group="points")
    assert [(r.product.name, r.offer.id) for r in pts.items] == [("Hotel", "h"), ("Both", "bp")]
    assert all(r.estimate.value_basis.startswith("estimated, assumes") for r in pts.items)


def test_a_fixed_cash_value_program_ranks_with_cash(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from bankrec.recommend import config, public_offers

    pv = {
        "default_cents_per_point": 1.0,
        "programs": {
            "Example Rewards": {
                "cents_per_point": 1.0,
                "basis": "Example Bank cash redemption page",
                "fixed_cash_value": True,
            }
        },
    }
    monkeypatch.setattr(config, "point_values", lambda: pv)
    monkeypatch.setattr(public_offers, "point_values", lambda: pv)
    fixed = card("Fixed", [offer("f")], reward_program="Example Rewards")
    [r] = rank([fixed], "credit_card", "value", NOW).items
    assert r.estimate.value_basis == "fixed value: 1.0¢ per point (Example Bank cash redemption page)"
