"""Wells Fargo adapter tests on verbatim official pages (tests/fixtures/wells_fargo/RETRIEVED.txt, 2026-11-09)."""

from decimal import Decimal

from tests.adapters._helpers import rates, run_official


def test_autograph() -> None:
    c = run_official("wells_fargo", "autograph", "autograph.html")
    assert c.parser_version == "wells_fargo/1.0.0"
    assert c.name == "Wells Fargo Autograph® Card"
    assert c.value("annual_fee_cents") == 0  # "$0 annual fee"
    assert (c.value("purchase_apr_min_pct"), c.value("purchase_apr_max_pct")) == (
        Decimal("18.74"),
        Decimal("28.74"),
    )
    r = rates(c)
    # tiles: "3X" / "on restaurants2", ... , "1X" / "on other purchases2"
    assert (
        r["dining"]
        == r["travel"]
        == r["gas"]
        == r["transit"]
        == r["streaming"]
        == r["telecom"]
        == ("3x", None)
    )
    assert r["other"] == ("1x", None)
    [o] = [o.value for o in c.offers if o.value]
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents, o.qualification_window_count) == (
        20000,
        "points",
        100000,
        3,
    )


def test_active_cash() -> None:
    c = run_official("wells_fargo", "active-cash", "active-cash.html")
    assert c.name == "Wells Fargo Active Cash® Card"
    assert rates(c)["other"] == ("2pct", None)
    assert c.value("foreign_tx_fee_pct") == Decimal(
        "3"
    )  # "There is a 3% fee for each foreign transaction ..."
    offers = [o.value for o in c.offers if o.value]
    assert {(o.amount_max, o.reward_unit, o.requirement_min_cents) for o in offers} == {
        (10000, "cents", 50000)
    }
    # the marketing-channel notice is never an offer
    assert not any(o.amount_max == 0 for o in offers)
