"""Personal offer check (DESIGN §27.10): the five acceptance personas, rule checks and the action levels.

Offers with made-up amounts use only the fictional Example Bank. Offers on real cards (Chase, Amex) carry no amounts
at all — those tests are about the real rules in config/tracker/rules.yaml, which are checked as they stand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from bankrec.tracker import config
from bankrec.tracker import views as TV
from bankrec.tracker.match import assess, questions
from bankrec.tracker.profile import HeldCard, MatchProfile
from bankrec.tracker.rules import CardFacts, evaluate

TODAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 9, 17, tzinfo=UTC)
RULES = config.rules()

FACTS = {
    "example_bank:everyday-cash": CardFacts("example_bank:everyday-cash", "example_bank", "consumer",
                                            "Example Bank Everyday Cash Card", annual_fee_cents=0),
    "example_bank:voyager-rewards": CardFacts("example_bank:voyager-rewards", "example_bank", "consumer",
                                              "Example Bank Voyager Rewards Card", annual_fee_cents=9500),
}  # fmt: skip
for c in config.cards():
    seg = "business" if ":business:" in c["canonical_key"] else "consumer"
    rp = (c.get("reports_to_personal_credit") or {}).get("value")
    FACTS[c["card_key"]] = CardFacts(
        c["card_key"], c["bank_id"], seg, c["card_key"], c.get("series"), rp, None
    )


def view(
    card_key: str,
    *,
    amount: int | None = None,
    unit: str = "cash",
    spend: int | None = None,
    months: int | None = None,
    fee: int | None = 0,
    program: str | None = None,
    value_cents: int | None = None,
    assumption: str | None = None,
    status: str = "active",
    starter: str | None = None,
) -> TV.CampaignView:
    f = FACTS[card_key]
    end = TV.moment({"date": None, "time": None, "time_known": False, "confirmed": False})
    assert end is not None
    tiers = [TV.Tier(amount=amount, unit=unit, spend_cents=spend, window_count=months,
                     window_unit="months" if months else None, window_start="account_opening")]  # fmt: skip
    terms = TV.Terms(
        offer_type="welcome_bonus", channel="public", tiers=tiers, total_amount=amount, unit=unit,
        min_spend_cents=spend, window_count=months, window_unit="months" if months else None,
        window_start="account_opening", annual_fee_cents=fee, first_year_fee_cents=fee, start=None, end=end,
        eligibility_text=None, verbatim=None, offer_url=None,
    )  # fmt: skip
    cents = value_cents if value_cents is not None else (amount if unit == "cash" else None)
    return TV.CampaignView(
        id="00000000-0000-0000-0000-000000000001", campaign_key=f"{card_key}|public|welcome_bonus",
        card=TV.CardSummary(card_key=card_key, product_id=None, name=f.name, bank_id=f.bank_id,
                            bank_name=f.bank_id, segment=f.segment, series=None, points_program=program,
                            points_program_name=None, official_url=None, annual_fee_cents=fee,
                            first_year_fee_cents=fee, reports_to_personal_credit=None,
                            counts_toward_chase_524=None, starter=starter,
                            demo=card_key.startswith("example_bank")),
        channel="public", channel_label="Public application", offer_type="welcome_bonus",
        offer_type_label="Welcome bonus", status=status, status_label=status, status_reason=None,
        source_kind="official", source_label="Official page", source_name=None, officially_verified=True,
        first_seen_at=NOW, last_checked_at=NOW, last_verified_at=NOW, version=1, terms=terms,
        deadline_label="Deadline unknown", countdown_to=None,
        value=TV.Value(cents=cents, depends_on_points_value=unit in ("points", "miles"), assumption=assumption,
                       cents_per_point=None, first_year_net_cents=None, first_year_fee_cents=fee),
        history=TV.HistoryLabel(code="insufficient_history", text="Not enough history recorded on this site yet.",
                                records=1, coverage_months=0, median=None, official_only=False),
        demo=True,
    )  # fmt: skip


def run(v: TV.CampaignView, p: MatchProfile) -> Any:
    return assess(v, FACTS[v.card.card_key], FACTS, RULES, p, TODAY)


FULL = {"credit_history": "5y_plus", "negative_marks": False, "credit_score": 760, "score_model": "fico",
        "cards_complete": True, "new_accounts_24m": 1, "monthly_spend": 3000, "max_annual_fee": 400}  # fmt: skip


# ----------------------------------------------------------------------------------- acceptance personas


def test_persona1_thin_file_student_is_not_told_to_apply_for_a_high_threshold_card() -> None:
    p = MatchProfile(credit_history="lt_1y", student=True, monthly_spend=600, cards=[], cards_complete=True,
                     new_accounts_24m=0)  # fmt: skip
    high = run(
        view("example_bank:voyager-rewards", amount=60000, unit="points", spend=400000, months=3, fee=9500), p
    )
    assert high.action == "not_suitable"
    assert high.reach.status == "insufficient"
    assert any("less than 1 year of credit history" in x for x in high.approval.points)
    assert any("not make approval easier" in x for x in high.approval.points)
    assert "Do not buy things you don't need" in high.reach.text
    low = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3), p)
    assert low.action == "improve_credit"  # reachable, but the short history comes first
    assert any("credit history" in r for r in low.action_reasons)
    assert low.approval.status == "credit_risk"


def test_persona2_five_new_cards_conflicts_with_chase_524() -> None:
    p = MatchProfile(**{**FULL, "new_accounts_24m": 5, "cards_complete": False})
    a = run(view("chase:sapphire-preferred"), p)
    assert a.action == "not_suitable"
    [c] = [c for c in a.conflicts if c.rule_key == "chase_5_24"]
    assert c.basis == "community" and "Community-reported" in c.basis_label
    assert a.approval.status == "known_conflict"
    assert a.eligibility[0].rule_key == "chase_5_24"  # the conflict is listed first
    assert any("5/24" in r and "Community-reported rule, widely corroborated" in r for r in a.action_reasons)


def test_persona3_amex_bonus_received_before_separates_approval_from_bonus() -> None:
    held = HeldCard(card_key="amex:blue-cash-preferred", bank_id="american_express", opened="2021-03",
                    open_now=False, bonus="yes", bonus_month="2021-06")  # fmt: skip
    p = MatchProfile(**{**FULL, "cards": [held]})
    a = run(view("amex:blue-cash-preferred"), p)
    # the once-per-lifetime wording is known only from a third party's quotation: "needs verification" (owner
    # 2026-11-10), shown as a bonus-eligibility issue, never as an approval conflict
    assert a.bonus.status == "needs_verification" and "Needs verification" in a.bonus.label
    assert a.approval.status == "no_known_conflict"
    assert a.approval.label != a.bonus.label
    assert any("does not estimate approval odds" in x for x in a.approval.points)
    assert a.conflicts == []
    [f] = [f for f in a.eligibility if f.rule_key == "amex_once_per_lifetime"]
    assert f.outcome == "needs_verification" and f.basis == "official" and f.effect == "bonus"
    assert f.verification == "third_party_quote" and f.officially_verified is False
    assert f.source_url.startswith("https://") and f.excerpt  # the original source is kept
    assert a.eligibility[0].rule_key == "amex_once_per_lifetime"  # listed first
    assert a.action == "verify_first"
    assert any("third party" in u for u in a.uncertainty)
    assert any("during the application" in x for x in a.bonus.points)  # the pop-up notice


def test_persona4_high_score_cannot_make_up_for_low_spending() -> None:
    p = MatchProfile(**{**FULL, "credit_score": 780, "monthly_spend": 800})
    a = run(view("example_bank:everyday-cash", amount=100000, spend=600000, months=3), p)
    assert a.reach.status == "insufficient" and a.reach.projected_cents == 240000
    assert a.action == "not_suitable"
    assert a.first_year.net_cents == 100000  # a large reward is shown, but it does not change the action


def test_persona5_score_only_gives_no_firm_answer() -> None:
    p = MatchProfile(credit_score=720)
    for key in ("chase:sapphire-preferred", "amex:blue-cash-preferred", "example_bank:everyday-cash"):
        a = run(view(key, amount=None, spend=None), p)
        assert a.action == "verify_first", key
        assert a.approval.status == "needs_info"
        assert a.uncertainty
    a = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3), p)
    assert a.action == "verify_first" and a.reach.status == "unknown"
    assert any("without its model" in x for x in a.approval.points)
    assert [q.key for q in questions(p)][:2] == ["credit_history", "monthly_spend"]


# ----------------------------------------------------------------------------------- action levels


def test_complete_answers_and_enough_spend_can_be_considered_now() -> None:
    a = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3), MatchProfile(**FULL))
    assert a.action == "consider_now"
    assert "$500" in a.action_reasons[0]


def test_tight_spend_without_margin_needs_confirmation() -> None:
    p = MatchProfile(**{**FULL, "monthly_spend": 1800})  # $5,400 in 3 months vs $5,000 (+20% = $6,000)
    a = run(view("example_bank:everyday-cash", amount=20000, spend=500000, months=3), p)
    assert a.reach.status == "tight" and a.action == "verify_first"


def test_high_reward_never_outweighs_an_official_conflict() -> None:
    held = HeldCard(card_key="chase:sapphire-preferred", bank_id="chase", opened="2020-01", open_now=True,
                    bonus="yes", bonus_month="2020-04")  # fmt: skip
    p = MatchProfile(**{**FULL, "cards": [held]})
    a = run(view("chase:sapphire-preferred", value_cents=10_000_000), p)
    assert a.action == "not_suitable"
    assert {c.rule_key for c in a.conflicts} >= {"chase_sapphire_card", "chase_sapphire_bonus"}
    assert a.conflicts[0].basis == "official"


def test_points_value_assumption_is_stated_in_first_year_value() -> None:
    v = view("example_bank:voyager-rewards", amount=20000, unit="points", spend=100000, months=3, fee=9500,
             program="example_points", value_cents=20000,
             assumption="Counted at 1 point = $0.01 (cash redemption value stated by Example Bank)")  # fmt: skip
    a = run(v, MatchProfile(**FULL))
    assert a.first_year.net_cents == 10500 and a.first_year.depends_on_points_value
    assert "1 point = $0.01" in a.first_year.text
    nov = run(view("example_bank:voyager-rewards", amount=20000, unit="points", spend=100000, months=3,
                   fee=9500, assumption="No dollar value: no official cash-redemption value"), MatchProfile(**FULL))  # fmt: skip
    assert nov.first_year.net_cents is None and "No dollar value" in nov.first_year.text


def test_business_card_without_business_income_is_not_a_fit() -> None:
    a = run(view("chase:ink-business-cash"), MatchProfile(**{**FULL, "business_income": "no"}))
    assert a.action == "not_suitable" and a.personal_fit.status == "poor"


def test_stale_offer_needs_confirmation() -> None:
    a = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3, status="stale"),
            MatchProfile(**FULL))  # fmt: skip
    assert a.action == "verify_first"


# ----------------------------------------------------------------------------------- rule checks


def rule(key: str) -> dict[str, Any]:
    return next(r for r in RULES if r["rule_key"] == key)


def check(key: str, card: str, **profile: Any) -> str:
    return evaluate(rule(key), FACTS[card], FACTS, MatchProfile(**profile), TODAY).outcome


def test_524_counts_authorized_user_cards_but_not_non_reporting_business_cards() -> None:
    au = [HeldCard(bank_id="other", opened=f"2026-0{m}", authorized_user=True) for m in range(1, 6)]
    assert check("chase_5_24", "chase:freedom-unlimited", cards=au) == "conflict"
    mixed = [*au[:4], HeldCard(card_key="chase:ink-business-cash", bank_id="chase", segment="business",
                               opened="2026-06")]  # fmt: skip
    assert check("chase_5_24", "chase:freedom-unlimited", cards=mixed, cards_complete=True) == "clear"
    old = [HeldCard(bank_id="other", opened="2023-01") for _ in range(6)]
    assert check("chase_5_24", "chase:freedom-unlimited", cards=old, cards_complete=True) == "clear"
    assert check("chase_5_24", "chase:freedom-unlimited", cards=old) == "unknown"  # list not complete
    assert check("chase_5_24", "chase:freedom-unlimited", new_accounts_24m=4) == "clear"


def test_boa_234_and_capital_one_interval() -> None:
    two = [
        HeldCard(bank_id="bank_of_america", opened="2026-10"),
        HeldCard(bank_id="bank_of_america", opened="2026-11"),
    ]
    # weakly corroborated community rules are only ever possible conflicts (owner 2026-11-10)
    assert check("boa_2_3_4", "boa:customized-cash", cards=two) == "possible_conflict"
    # month precision: a card opened exactly at the window's edge cannot settle it
    edge = [two[0], HeldCard(bank_id="bank_of_america", opened="2026-09")]
    assert check("boa_2_3_4", "boa:customized-cash", cards=edge, cards_complete=True) == "unknown"
    assert check("boa_2_3_4", "boa:customized-cash", cards=two[:1], cards_complete=True) == "clear"
    assert check("boa_2_3_4", "boa:customized-cash", new_accounts_24m=0) == "clear"
    assert check("boa_2_3_4", "boa:customized-cash", new_accounts_24m=3) == "unknown"
    c1 = [HeldCard(bank_id="capital_one", opened="2026-08")]
    assert check("capital_one_1_per_6", "capital_one:savor", cards=c1) == "possible_conflict"


def test_citi_48_month_lookback_and_product_change() -> None:
    old = HeldCard(
        card_key="citi:double-cash", bank_id="citi", opened="2020-01", bonus="yes", bonus_month="2020-03"
    )
    assert check("citi_double_cash_48", "citi:double-cash", cards=[old], cards_complete=True) == "clear"
    recent = old.model_copy(update={"bonus_month": "2024-01"})
    assert check("citi_double_cash_48", "citi:double-cash", cards=[recent]) == "conflict"
    pc = HeldCard(card_key="citi:double-cash", bank_id="citi", product_change=True, bonus="no",
                  original_bonus_month="2025-02")  # fmt: skip
    assert check("citi_double_cash_48", "citi:double-cash", cards=[pc]) == "conflict"
    unsure = old.model_copy(update={"bonus": "unknown", "bonus_month": None})
    assert check("citi_double_cash_48", "citi:double-cash", cards=[unsure]) == "unknown"


def test_sapphire_rules_are_per_card_and_holding_preferred_does_not_block_reserve() -> None:
    """Owner 2026-11-11, from both Sapphire pages read that day: approval needs this same card not to be open, the
    bonus is once per card; the other Sapphire card is not named. No family or 48-month rule remains."""
    keys = {r["rule_key"] for r in RULES if r["bank_id"] == "chase" and "sapphire" in r["rule_key"]}
    assert keys == {"chase_sapphire_card", "chase_sapphire_bonus"}
    assert not any("48" in str(r.get("window_months") or "") for r in RULES if "sapphire" in r["rule_key"])
    csp = HeldCard(card_key="chase:sapphire-preferred", bank_id="chase", opened="2024-02", open_now=True,
                   bonus="yes", bonus_month="2024-04")  # fmt: skip
    p = MatchProfile(**{**FULL, "cards": [csp]})
    reserve = run(view("chase:sapphire-reserve"), p)
    sapphire = [f for f in reserve.eligibility if "sapphire" in f.rule_key]
    assert {f.outcome for f in sapphire} == {"clear"}
    assert reserve.bonus.status == "no_known_conflict" and not reserve.conflicts
    # the same card: approval blocked while open, bonus not available after having it
    preferred = run(view("chase:sapphire-preferred"), p)
    assert {c.rule_key for c in preferred.conflicts} == {"chase_sapphire_card", "chase_sapphire_bonus"}
    # a closed Preferred whose bonus was earned years ago still does not touch the Reserve
    closed = csp.model_copy(update={"open_now": False, "bonus_month": "2019-04", "opened": "2019-01"})
    again = run(view("chase:sapphire-reserve"), MatchProfile(**{**FULL, "cards": [closed]}))
    assert not again.conflicts and again.bonus.status == "no_known_conflict"


@pytest.mark.parametrize(
    "score,expected", [(560, "credit_risk"), (640, "no_known_conflict"), (800, "no_known_conflict")]
)
def test_score_is_a_signal_never_a_cutoff(score: int, expected: str) -> None:
    a = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3),
            MatchProfile(**{**FULL, "credit_score": score}))  # fmt: skip
    assert a.approval.status == expected
    assert any("not the only factor" in x or "does not decide approval" in x for x in a.approval.points)


# ----------------------------------------------------------------------------------- owner decisions 2026-11-10


def test_every_community_rule_has_a_confidence_and_official_rules_none() -> None:
    for r in RULES:
        if r["source_type"] == "community":
            assert r.get("confidence") in ("strong", "weak"), r["rule_key"]
        else:
            assert "confidence" not in r, r["rule_key"]
    assert rule("chase_5_24")["confidence"] == "strong"
    assert {
        rule(k)["confidence"] for k in ("boa_2_3_4", "capital_one_1_per_6", "capital_one_two_personal")
    } == {"weak"}


def test_weak_community_rule_met_means_confirm_first_and_is_labelled() -> None:
    two = [
        HeldCard(bank_id="bank_of_america", opened="2026-10"),
        HeldCard(bank_id="bank_of_america", opened="2026-11"),
    ]
    a = run(view("boa:customized-cash"), MatchProfile(**{**FULL, "cards": two, "new_accounts_24m": 2}))
    assert a.action == "verify_first"
    assert not a.conflicts
    [f] = [f for f in a.eligibility if f.rule_key == "boa_2_3_4"]
    assert f.outcome == "possible_conflict" and f.confidence == "weak"
    assert any("2/3/4" in r and "Community-reported rule, less established" in r for r in a.action_reasons)


def test_amex_third_party_quote_is_marked_not_officially_verified() -> None:
    held = HeldCard(card_key="amex:blue-cash-preferred", bank_id="american_express", opened="2021-03",
                    open_now=False, bonus="yes", bonus_month="2021-06")  # fmt: skip
    a = run(view("amex:blue-cash-preferred"), MatchProfile(**{**FULL, "cards": [held]}))
    [f] = [f for f in a.eligibility if f.rule_key == "amex_once_per_lifetime"]
    assert f.officially_verified is False and "not officially verified" in f.basis_label
    assert f.outcome_label == "Needs verification"
    assert any("not officially verified" in r for r in a.action_reasons)
    sapphire = finding_for("chase_sapphire_card", "chase:sapphire-preferred")
    assert sapphire.officially_verified is True


def finding_for(key: str, card: str) -> Any:
    from bankrec.tracker.match import finding_view

    return finding_view(evaluate(rule(key), FACTS[card], FACTS, MatchProfile(), TODAY))


def test_boundary_month_needs_checking_never_clear() -> None:
    # four cards clearly inside 24 months, one opened exactly 24 months ago (2024-11): inside or outside by the day
    recent = [HeldCard(bank_id="other", opened=f"2026-0{m}") for m in range(1, 5)]
    edge = HeldCard(bank_id="other", opened="2024-11")
    p = MatchProfile(**{**FULL, "new_accounts_24m": None, "cards": [*recent, edge], "cards_complete": True})
    f = evaluate(rule("chase_5_24"), FACTS["chase:freedom-unlimited"], FACTS, p, TODAY)
    assert f.outcome == "unknown" and f.boundary and "exactly 24 months ago" in f.explanation
    a = run(view("chase:freedom-unlimited"), p)
    [fv] = [x for x in a.eligibility if x.rule_key == "chase_5_24"]
    assert fv.outcome_label == "Needs checking (boundary month)"
    assert a.action == "verify_first"
    # the month after the boundary is clearly outside; the month before clearly inside
    outside = p.model_copy(update={"cards": [*recent, HeldCard(bank_id="other", opened="2024-10")]})
    assert (
        evaluate(rule("chase_5_24"), FACTS["chase:freedom-unlimited"], FACTS, outside, TODAY).outcome
        == "clear"
    )
    inside = p.model_copy(update={"cards": [*recent, HeldCard(bank_id="other", opened="2024-12")]})
    assert (
        evaluate(rule("chase_5_24"), FACTS["chase:freedom-unlimited"], FACTS, inside, TODAY).outcome
        == "conflict"
    )
    # a bonus received exactly 48 months ago (Citi)
    dc = HeldCard(
        card_key="citi:double-cash", bank_id="citi", opened="2022-09", bonus="yes", bonus_month="2022-11"
    )
    g = evaluate(rule("citi_double_cash_48"), FACTS["citi:double-cash"], FACTS,
                 MatchProfile(cards=[dc], cards_complete=True), TODAY)  # fmt: skip
    assert g.outcome == "unknown" and g.boundary


def test_income_range_is_optional_and_never_a_cutoff() -> None:
    v = view("example_bank:everyday-cash", amount=20000, spend=50000, months=3)
    none_given = run(v, MatchProfile(**FULL))
    assert any("not given an income range" in u for u in none_given.uncertainty)
    assert none_given.action == "consider_now"
    given = run(v, MatchProfile(**{**FULL, "annual_income": "50k_100k"}))
    assert given.action == "consider_now"
    assert any("publish no minimum income" in x for x in given.approval.points)
    no_income = run(v, MatchProfile(**{**FULL, "annual_income": "none", "student": True}))
    assert no_income.action == "verify_first"
    assert any("12 CFR 1026.51" in x for x in no_income.approval.points)
    assert any("under 21" in x for x in no_income.approval.points)
    over = run(v, MatchProfile(**{**FULL, "annual_income": "lt_25k", "monthly_spend": 3000}))
    assert over.action == "verify_first"
    assert any("above the income range" in r for r in over.action_reasons)


def test_starter_cards_are_tracked_with_registered_sources() -> None:
    from bankrec.registry.loader import load_registry

    ids = {s.source_id for s in load_registry().sources}
    starters = {c["card_key"]: c for c in config.cards() if c.get("starter")}
    assert set(starters) == {"discover:it-student-cash-back", "capital_one:savor-student",
                             "capital_one:quicksilver-student", "capital_one:platinum-secured",
                             "capital_one:quicksilver-secured"}  # fmt: skip
    for c in starters.values():
        assert c["starter"] in ("student", "secured") and set(c["source_ids"]) <= ids
    assert {"amex:gold", "capital_one:venture-x"} <= {c["card_key"] for c in config.cards()}


THIN = {"credit_history": "lt_1y", "student": True, "monthly_spend": 600, "cards": [], "cards_complete": True,
        "new_accounts_24m": 0, "negative_marks": False}  # fmt: skip


def test_thin_file_is_pointed_to_starter_cards_without_calling_approval_easy() -> None:
    p = MatchProfile(**THIN)
    student = run(view("capital_one:savor-student", amount=5000, spend=10000, months=3, starter="student"), p)
    assert student.action in ("consider_now", "verify_first")
    assert student.action != "improve_credit" and student.starter == "student"
    assert any("does not mean approval is easy" in x for x in student.approval.points)
    regular = run(view("example_bank:everyday-cash", amount=20000, spend=50000, months=3), p)
    assert regular.action == "improve_credit"
    assert any("Starter cards" in r for r in regular.action_reasons)


def test_card_without_offer_gets_approval_and_fit_only() -> None:
    from bankrec.tracker.match import assess_card

    cv = view("capital_one:platinum-secured", starter="secured").card
    p = MatchProfile(**{**THIN, "negative_marks": True})
    a = assess_card(cv, FACTS["capital_one:platinum-secured"], FACTS, RULES, p, TODAY, now=NOW)
    assert a.kind == "card" and a.campaign_id is None
    assert a.bonus.status == "no_offer" and a.reach.status == "not_required"
    assert all(f.effect == "approval" for f in a.eligibility)
    # negative marks are a caution on a secured card, never a promise
    assert a.action != "improve_credit"
    assert any("refundable deposit" in x for x in a.approval.points)


def test_valuation_own_value_exact_offer_and_up_to_offer() -> None:
    from bankrec.tracker.valuation import value

    exact = {"unit": "points", "total_amount": 60000, "amount_qualifier": "exact"}
    v = value(exact, "example_points", {"example_points": 1.5})
    assert v["cents"] == 90000 and "your own value" in v["assumption"]
    upto = {**exact, "amount_qualifier": "up_to"}
    u = value(upto, "example_points", {"example_points": 1.5})
    assert (
        u["cents"] is None and "up to 60,000" in u["assumption"] and "varies by applicant" in u["assumption"]
    )


def test_third_party_rule_becomes_a_conflict_only_once_the_issuer_confirms_it() -> None:
    held = HeldCard(card_key="amex:blue-cash-preferred", bank_id="american_express", opened="2021-03",
                    open_now=False, bonus="yes", bonus_month="2021-06")  # fmt: skip
    p = MatchProfile(cards=[held])
    quoted = rule("amex_once_per_lifetime")
    assert (
        evaluate(quoted, FACTS["amex:blue-cash-preferred"], FACTS, p, TODAY).outcome == "needs_verification"
    )
    confirmed = {**quoted, "verification": "page_captured"}  # as if read on the issuer's own terms
    assert evaluate(confirmed, FACTS["amex:blue-cash-preferred"], FACTS, p, TODAY).outcome == "conflict"


# ----------------------------------------------------------------------------------- owner decisions 2026-11-11


def _entry(name: str) -> Any:
    import yaml

    from bankrec.tracker.manual import ManualCampaignIn

    return ManualCampaignIn.model_validate(
        yaml.safe_load((config.DIR / "manual_entries" / name).read_text(encoding="utf-8"))
    )


def test_venture_stays_credit_is_a_separate_restricted_component() -> None:
    from bankrec.tracker import terms as T
    from bankrec.tracker.valuation import value

    t = _entry("2026-11-10-capital-one-venture.yaml").to_terms()
    [c] = t["offer_components"]
    assert c["amount_cents"] == 30000 and c["kind"] == "travel_credit"
    assert c["restriction"] == "hotel and vacation rental bookings through Capital One Travel"
    assert c["expires"] == "in your first cardholder year"
    # the miles stay miles; the credit is never added to them nor counted as cash
    assert t["total_amount"] == 75000 and t["unit"] == "miles"
    v = value(t, "c1_miles", {"c1_miles": 1.0})
    assert v["cents"] == 75000  # 75,000 miles at the visitor's 1¢ — the $300 credit is not in it
    # the component is a material term: changing it makes a new version, its wording alone does not
    other = {**t, "offer_components": [{**c, "amount_cents": 25000}]}
    assert T.material_hash(other) != T.material_hash(t)
    reworded = {**t, "offer_components": [{**c, "text": c["text"] + " (see terms)"}]}
    assert T.material_hash(reworded) == T.material_hash(t)
    # offers read before offer_components existed hash as they did
    old = {k: x for k, x in t.items() if k != "offer_components"}
    assert T.material_hash({**old, "offer_components": []}) == T.material_hash(old)


def test_component_is_shown_apart_in_the_check() -> None:
    v = view("example_bank:everyday-cash", amount=20000, spend=50000, months=3)
    comp = TV.Component(kind="travel_credit", amount_cents=30000, restriction="hotel bookings through Example Travel",
                        expires="in your first cardholder year", text="Enjoy $300 for hotel bookings.")  # fmt: skip
    v = v.model_copy(update={"terms": v.terms.model_copy(update={"offer_components": [comp]})})
    a = run(v, MatchProfile(**FULL))
    assert a.first_year.net_cents == 20000  # the $300 credit is not in the net value
    assert "Not counted above: $300 credit for hotel bookings through Example Travel" in a.first_year.text
    assert any("restricted, not cash and not converted to points" in x for x in a.offer_appeal.points)


def test_amex_gold_is_a_variable_offer_without_a_guaranteed_minimum() -> None:
    from bankrec.tracker.valuation import guaranteed_amount, value

    t = _entry("2026-11-10-amex-gold.yaml").to_terms()
    assert t["amount_qualifier"] == "up_to" and t["total_amount"] == 100000 and t["guaranteed_min"] is None
    assert guaranteed_amount(t) is None
    for overrides in (None, {"amex_mr": 1.0}):  # not even at the visitor's own point value
        v = value(t, "amex_mr", overrides)
        assert v["cents"] is None and "varies by applicant" in v["assumption"]
    assert "AS HIGH AS 100,000" in t["verbatim"]


def test_published_guaranteed_minimum_is_the_only_amount_used() -> None:
    from bankrec.tracker import history
    from bankrec.tracker.valuation import guaranteed_amount, value

    t = {"unit": "cash", "total_amount": 50000, "amount_qualifier": "up_to", "guaranteed_min": 20000}
    assert guaranteed_amount(t) == 20000
    v = value(t, None)
    assert v["cents"] == 20000 and "published minimum of 20,000" in v["assumption"]
    # "starting at N" publishes N as its minimum
    assert guaranteed_amount({"total_amount": 30000, "amount_qualifier": "starting_at"}) == 30000
    # history compares the minimum, so a variable offer's top figure can never make it the "highest"
    past = [history.Record(amount=a, unit="cash", valid_from=datetime(2025, m, 1, tzinfo=UTC),
                           valid_to=datetime(2025, m, 28, tzinfo=UTC), official=True) for a, m in ((25000, 1), (30000, 4), (25000, 8))]  # fmt: skip
    current = history.Record(amount=guaranteed_amount(t) or 0, unit="cash", valid_from=NOW, valid_to=None,
                             official=True, current=True)  # fmt: skip
    assert history.label([*past, current], NOW)["code"] == "below_usual"


def test_manual_entry_validation_for_minimums() -> None:
    from bankrec.tracker.manual import ManualCampaignIn

    base = _entry("2026-11-10-amex-gold.yaml").model_dump(mode="json")
    with pytest.raises(ValueError, match="guaranteed_min_text"):
        ManualCampaignIn.model_validate({**base, "guaranteed_min": 50000})
    with pytest.raises(ValueError, match="only for an up-to"):
        ManualCampaignIn.model_validate({**base, "amount_qualifier": "exact", "guaranteed_min": 1,
                                         "guaranteed_min_text": "at least 1 point"})  # fmt: skip


def test_third_party_history_is_labelled_and_can_be_excluded() -> None:
    from bankrec.tracker import history

    def rec(a: int, y: int, m: int, official: bool, current: bool = False) -> history.Record:
        start = datetime(y, m, 1, tzinfo=UTC)
        return history.Record(amount=a, unit="points", valid_from=start, current=current, official=official,
                              valid_to=None if current else datetime(y, m, 28, tzinfo=UTC))  # fmt: skip

    recs = [
        rec(125000, 2025, 8, False),
        rec(150000, 2026, 4, False),
        rec(100000, 2026, 6, True, current=True),
    ]
    mixed = history.label(recs, NOW)
    assert mixed["code"] == "below_usual" and "including third-party records" in mixed["text"]
    assert "In the history recorded on this site" in mixed["text"]
    # official records only: not enough history for any comparison
    assert history.label(recs, NOW, official_only=True)["code"] == "insufficient_history"
