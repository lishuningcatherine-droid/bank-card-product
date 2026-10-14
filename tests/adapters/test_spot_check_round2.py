"""Regression tests for the owner's spot check, round 2 (docs/SPOT_CHECK.md round 2, DESIGN §24.17), built from the
stored snapshots of 2026-10-14. Each test names its finding; values were read off the snapshot text by hand."""

from __future__ import annotations

from bankrec.ingest.common import extract as X
from bankrec.model import NullReason
from tests.adapters._helpers import run_official


def offers(c):  # type: ignore[no-untyped-def]
    return [o.value for o in c.offers if o.value]


def window(o):  # type: ignore[no-untyped-def]
    return (o.qualification_window_count, o.qualification_window_unit, o.qualification_window_days)


def test_c_sapphire_reserve_window_stays_3_months() -> None:
    # «Earn 100,000 points after you spend $6,000 in purchases in the first 3 months from account opening»
    c = run_official("chase", "chase-sapphire-reserve", "sapphire-reserve-2026-10-14.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.requirement_min_cents) == (100000, 600000)
    assert window(o) == (3, "months", None) and o.qualification_window_months == 3


def test_c_quicksilver_student_window_stays_3_months() -> None:
    # «Earn a one-time $50 cash bonus once you spend $100 on purchases within 3 months from account opening»
    c = run_official("capital_one", "quicksilver-student", "quicksilver-student-2026-10-14.html")
    [o] = offers(c)
    assert (o.amount_max, o.reward_unit, o.requirement_min_cents) == (5000, "cents", 10000)
    assert window(o) == (3, "months", None)


def test_c_ihg_window_stays_3_months() -> None:
    # «Earn 125,000 Bonus Points after you spend $2,000 on purchases in the first 3 months from account opening.»
    c = run_official("chase", "ihg-one-rewards", "ihg-one-rewards-2026-10-14.rendered.html")
    [o] = offers(c)
    assert (o.amount_max, o.requirement_min_cents) == (125000, 200000)
    assert window(o) == (3, "months", None)


def test_d_savor_good_credit_no_offer_is_stated_by_issuer() -> None:
    # «You’ll earn the usual Savor grocery store, dining and entertainment rewards, but won’t be eligible for new
    # cardmember bonus cash or 0% intro APR»: a stated absence, not "not captured".
    c = run_official("capital_one", "savor-good-credit", "savor-good-credit-2026-10-14.html")
    assert offers(c) == [] and c.offer_status == "none_stated"
    cap = c.fields["offer_capture"]
    assert (
        cap.value is True
        and cap.span_text is not None
        and "won’t be eligible for new cardmember bonus" in cap.span_text
    )
    assert c.offer_absent_note is not None and c.offer_absent_note.startswith(
        "No welcome offer (stated by Capital One)"
    )
    assert c.fields["intro_purchase_apr_pct"].null_reason is NullReason.not_applicable


def test_d_eligibility_rules_are_not_a_stated_absence() -> None:
    assert (
        X.no_offer_statement(
            "The new cardmember bonus may not be available to you if you previously held this card."
        )
        is None
    )
    assert X.no_offer_statement("You are not eligible for a welcome offer if you have had this Card.") is None
    assert (
        X.no_offer_statement("This card does not offer a welcome bonus.")
        == "This card does not offer a welcome bonus."
    )
