"""Deadlines in ET, the status machine, history labels and valuation (DESIGN §27). No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bankrec.tracker import deadline, history, status, terms, valuation

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------------ deadlines (acceptance: ET, no invented times)
def test_unknown_deadline_has_no_end_and_no_countdown() -> None:
    m = deadline.end_from_offer(
        "Earn 60,000 bonus points after spending $4,000 in the first 3 months.", None, None
    )
    assert m["date"] is None and m["confirmed"] is False
    assert deadline.instant(m) is None
    assert deadline.label(m) == "Deadline unknown"


def test_date_only_is_never_filled_in_as_2359() -> None:
    m = deadline.end_from_offer("Offer ends 12/5/2026.", None, None)
    assert (m["date"], m["time"], m["time_known"]) == ("2026-12-05", None, False)
    assert deadline.label(m) == "Deadline 2026-12-05 (time not published)"
    assert "23:59" not in deadline.label(m)
    assert m["text"] == "Offer ends 12/5/2026."  # the original wording is kept


def test_stated_time_is_shown_in_et() -> None:
    m = deadline.moment("Apply by December 5, 2026 at 11:59 p.m. ET to get this offer.")
    assert m is not None and deadline.label(m) == "Deadline: 2026-12-05 23:59 ET"
    pt = deadline.moment("This offer expires on March 3, 2027 at 9 a.m. PT.")
    assert pt is not None and deadline.label(pt) == "Deadline: 2027-03-03 12:00 ET"  # converted, zone kept
    assert pt["stated_tz"] == "PT"


def test_time_without_zone_is_not_called_et() -> None:
    m = deadline.moment("Offer ends 12/05/26 at 5pm.")
    assert m is not None and "ET" not in deadline.label(m)


# ------------------------------------------------------------------ status machine (acceptance: failures never end)
END_SOON = {"date": "2026-11-20", "time": None, "time_known": False, "confirmed": True}
END_PAST = {"date": "2026-11-01", "time": None, "time_known": False, "confirmed": True}
END_UNCONFIRMED = {"date": "2026-11-01", "time": None, "time_known": False, "confirmed": False}


def _st(current: str = "active", **kw):  # type: ignore[no-untyped-def]
    args = {"end": None, "now": NOW, "last_verified_at": NOW - timedelta(days=1), "consecutive_failures": 0,
            "not_seen": False} | kw  # fmt: skip
    return status.compute(current, **args)


def test_one_failed_check_keeps_the_status() -> None:
    assert _st(consecutive_failures=1)[0] == "active"


def test_repeated_failures_make_data_stale_never_expired() -> None:
    st, why = _st(consecutive_failures=3)
    assert st == "stale" and "not treated as ended" in why
    assert _st(last_verified_at=NOW - timedelta(days=8))[0] == "stale"


def test_not_seen_needs_verification_not_ended() -> None:
    assert _st(not_seen=True)[0] == "pending_verification"


def test_expiry_only_from_a_confirmed_deadline() -> None:
    assert _st(end=END_PAST)[0] == "expired"
    assert _st(end=END_UNCONFIRMED)[0] == "active"
    assert _st(end=None)[0] == "active"


def test_ending_soon_only_with_a_confirmed_date() -> None:
    assert _st(end=END_SOON)[0] == "ending_soon"
    assert _st(end={**END_SOON, "confirmed": False})[0] == "active"


def test_reviewer_decisions_are_kept() -> None:
    assert _st("withdrawn")[0] == "withdrawn"


# ------------------------------------------------------------------ history labels (acceptance: no label without history)
def _rec(amount: int, months_ago: float, current: bool = False, official: bool = True) -> history.Record:
    start = NOW - timedelta(days=months_ago * 30.4375)
    return history.Record(
        amount, "points", start, None if current else start + timedelta(days=20), official, current
    )


def test_no_comparative_label_without_three_records_over_twelve_months() -> None:
    assert history.label([_rec(80000, 1, current=True)], NOW)["code"] == "insufficient_history"
    few = [_rec(60000, 6), _rec(75000, 3), _rec(90000, 0.5, current=True)]
    out = history.label(few, NOW)
    assert out["code"] == "insufficient_history" and "highest" not in out["text"].lower()


def test_labels_with_enough_history_say_they_are_about_this_sites_records() -> None:
    recs = [_rec(60000, 20), _rec(60000, 14), _rec(75000, 8), _rec(100000, 0.5, current=True)]
    out = history.label(recs, NOW)
    assert out["code"] == "all_time_high"
    assert out["text"].startswith("In the history recorded on this site")


def test_third_party_records_are_distinguished() -> None:
    recs = [
        _rec(60000, 20, official=False),
        _rec(60000, 14, official=False),
        _rec(75000, 8),
        _rec(100000, 0.5, current=True),
    ]
    assert "third-party" in history.label(recs, NOW)["text"]
    assert history.label(recs, NOW, official_only=True)["code"] == "insufficient_history"


# ------------------------------------------------------------------ valuation (acceptance: assumptions shown)
def test_points_without_an_official_floor_have_no_dollar_value() -> None:
    v = valuation.value({"unit": "points", "total_amount": 75000}, "chase_ur")
    assert v["cents"] is None and v["depends_on_points_value"]
    assert "No dollar value" in v["assumption"]


def test_points_with_an_official_floor_state_the_assumption() -> None:
    v = valuation.value({"unit": "points", "total_amount": 20000}, "wf_rewards")
    assert v["cents"] == 20000 and v["assumption"].startswith("Counted at 1 point = $0.01")


def test_visitor_value_overrides_and_cash_needs_no_assumption() -> None:
    v = valuation.value({"unit": "points", "total_amount": 75000}, "chase_ur", {"chase_ur": 1.25})
    assert v["cents"] == 93750 and "your own value" in v["assumption"]
    cash = valuation.value({"unit": "cash", "total_amount": 20000}, None)
    assert cash["cents"] == 20000 and cash["assumption"] is None and not cash["depends_on_points_value"]


# ------------------------------------------------------------------ identity and material changes
BASE = {"offer_type": "welcome_bonus", "channel": "public", "unit": "points", "requirement_type": "spend",
        "tiers": [{"amount": 75000, "unit": "points", "spend_cents": 500000, "window_count": 3,
                   "window_unit": "months", "window_start": "account_opening", "text": "Earn 75,000 points"}],
        "total_amount": 75000, "min_spend_cents": 500000, "window_count": 3, "window_unit": "months",
        "window_start": "account_opening", "annual_fee_cents": 9500, "first_year_fee_cents": 9500,
        "end": deadline.unknown(), "start": None, "eligibility_text": "x", "channels_seen": ["product_page"],
        "verbatim": "Earn 75,000 points after you spend $5,000."}  # fmt: skip


def test_wording_changes_are_not_material() -> None:
    reworded = {**BASE, "verbatim": "EARN 75,000 POINTS — limited time!", "channels_seen": ["offer_page"],
                "tiers": [{**BASE["tiers"][0], "text": "different layout"}]}  # fmt: skip
    assert terms.material_hash(reworded) == terms.material_hash(BASE)


@pytest.mark.parametrize(
    "change",
    [
        {"total_amount": 100000},
        {"min_spend_cents": 600000},
        {"window_count": 6},
        {"first_year_fee_cents": 0},
        {"end": {"date": "2027-01-22", "time": None, "time_known": False, "confirmed": True}},
        {"eligibility_text": "not available if you have had this card"},
    ],
)
def test_material_changes_make_a_new_version_of_the_same_campaign(change) -> None:  # type: ignore[no-untyped-def]
    new = {**BASE, **change}
    assert terms.material_hash(new) != terms.material_hash(BASE)
    assert terms.campaign_key("x:card", new) == terms.campaign_key("x:card", BASE)  # same campaign


def test_channel_or_structure_make_a_different_campaign() -> None:
    assert terms.campaign_key("x:card", {**BASE, "channel": "targeted"}) != terms.campaign_key("x:card", BASE)
    assert terms.campaign_key("x:card", {**BASE, "unit": "cash"}) != terms.campaign_key("x:card", BASE)
