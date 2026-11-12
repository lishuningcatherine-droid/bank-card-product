"""Review evidence (owner 2026-11-11): stored fields compared with the official page's words. Fictional Example Bank
text only."""

from __future__ import annotations

from typer.testing import CliRunner

from bankrec.tracker.evidence import compare
from bankrec.tracker.manual import ManualCampaignIn

PAGE = (
    "Example Bank Voyager Rewards Card. New Cardmember Offer: Earn 60,000 bonus points after you spend $4,000 on"
    " purchases in the first 3 months from account opening. Plus $200 to use on hotel bookings through Example"
    " Travel in your first cardholder year. $95 annual fee; $45 for each authorized user. The annual fee for each"
    " Additional Card is $0 annual fee for the first five. You may not be eligible if you had this card."
)
ENTRY = {
    "card_key": "example_bank:voyager-rewards", "channel": "public", "offer_type": "welcome_bonus",
    "tiers": [{"amount": 60000, "unit": "points", "unit_name": "Example Rewards points", "spend_cents": 400000,
               "window_count": 3, "window_unit": "months", "window_start": "account_opening",
               "text": "Earn 60,000 bonus points after you spend $4,000 on purchases in the first 3 months from account opening."}],
    "offer_components": [{"kind": "travel_credit", "amount_cents": 20000, "restriction": "hotel bookings through Example Travel",
                          "expires": "in your first cardholder year",
                          "text": "Plus $200 to use on hotel bookings through Example Travel in your first cardholder year"}],
    "annual_fee_cents": 9500, "first_year_fee_cents": 9500,
    "eligibility_text": "You may not be eligible if you had this card.",
    "source_kind": "official", "source_url": "https://www.examplebank.example/cards/voyager",
    "source_excerpt": "Earn 60,000 bonus points after you spend $4,000", "observed_from": "2026-11-10", "demo": True,
}  # fmt: skip


def verdicts(entry: dict, page: str = PAGE) -> dict[str, str]:  # type: ignore[type-arg]
    return {r.field: r.verdict for r in compare(ManualCampaignIn.model_validate(entry), page)}


def test_every_field_matches_the_page() -> None:
    v = verdicts(ENTRY)
    assert set(v.values()) == {"match"}, v
    # the authorized-user and additional-card fees are not the card's annual fee
    assert v["annual fee"] == "match"


def test_wrong_values_are_reported_as_mismatches() -> None:
    wrong = {**ENTRY, "annual_fee_cents": 12500, "first_year_fee_cents": 0,
             "tiers": [{**ENTRY["tiers"][0], "spend_cents": 300000}]}  # fmt: skip
    v = verdicts(wrong)
    assert v["annual fee"] == "mismatch" and v["first-year fee"] == "mismatch"
    assert v["offer: spend requirement"] == "mismatch"


def test_text_missing_from_the_page_is_never_a_match() -> None:
    v = verdicts(ENTRY, page="Example Bank Voyager Rewards Card. $95 annual fee.")
    assert v["offer: offer sentence (verbatim)"] == "not on page"
    assert v["offer: amount"] == "mismatch" and v["component: sentence (verbatim)"] == "not on page"


def test_stated_deadline_must_be_on_the_page() -> None:
    v = verdicts(ENTRY, page=PAGE + " Offer ends December 5, 2026.")
    assert v["application deadline"] == "mismatch"  # the page states an end date the entry does not have


def test_check_target_never_prints_the_connection_string(db_url: str, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from bankrec.cli.main import app
    from bankrec.db.session import engine_for
    from bankrec.settings import get_settings

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    engine_for.cache_clear()
    try:
        out = CliRunner().invoke(app, ["db", "check-target"]).output
    finally:
        get_settings.cache_clear()
        engine_for.cache_clear()
    assert '"server_version"' in out
    assert db_url not in out and "@" not in out and "postgresql" not in out


def test_component_spending_condition_is_checked_in_its_own_sentence() -> None:
    assert verdicts(ENTRY)["component: spending requirement"] == "match"
    tied = "Get $200 for hotel bookings through Example Travel in your first cardholder year after you spend $1,000"
    page = PAGE.replace(ENTRY["offer_components"][0]["text"], tied)  # type: ignore[index]
    entry = {**ENTRY, "offer_components": [{**ENTRY["offer_components"][0], "text": tied}]}  # type: ignore[index]
    assert verdicts(entry, page)["component: spending requirement"] == "mismatch"


def test_spelled_out_numbers_count_as_the_same_window() -> None:
    from bankrec.tracker.evidence import _says

    assert _says("after spending $6,000 within the first three months", "3 months")
    assert not _says("after spending $6,000 within the first six months", "3 months")


def test_versions_listing_is_read_only_and_prints_no_address(db_url: str, engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from bankrec.cli.main import app
    from bankrec.db.session import engine_for
    from bankrec.settings import get_settings

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    engine_for.cache_clear()
    try:
        res = CliRunner().invoke(app, ["offers", "versions", "--since", "2026-11-12"])
    finally:
        get_settings.cache_clear()
        engine_for.cache_clear()
    assert res.exit_code == 0, res.output
    assert "no versions since 2026-11-12T00:00:00+00:00" in res.output
    assert db_url not in res.output and "postgresql" not in res.output
