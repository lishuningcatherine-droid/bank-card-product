"""rewards_program = "none": evidence-backed only, owner-confirmed, limited goals (config/no_rewards.yaml, DESIGN §24.15)."""

from __future__ import annotations

import pytest

from bankrec.model import NullReason
from bankrec.recommend import cards
from bankrec.registry.no_rewards import confirmed, entries, verify
from tests.adapters._helpers import run_official
from tests.unit.test_recommend_cards import NOW, card, req

SECURED = (
    "bank_of_america",
    "secured-credit-card",
    "credit-cards-products-secured-credit-card.rendered.html",
)
UNLIMITED = (
    "bank_of_america",
    "unlimited-cash-back-credit-card",
    "credit-cards-products-unlimited-cash-back-credit-card.rendered.html",
)


def test_every_entry_has_positive_evidence_that_verifies() -> None:
    checks = verify()
    assert checks and all(c.ok for c in checks), [c for c in checks if not c.ok]
    for e in entries():
        crit = {c.criterion for c in checks if (c.bank_id, c.slug) == (e["bank_id"], e["slug"])}
        assert {
            "a",
            "b",
        } <= crit  # listed on a low-interest/credit-building page AND absent from rewards pages


def test_nothing_is_recorded_until_the_owner_confirms() -> None:
    assert confirmed() == set()  # all entries pending (2026-10-14)
    c = run_official(*SECURED)
    assert "rewards_program" not in c.fields and c.value("base_rate") is None


def test_confirmed_entry_sets_none_and_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    import bankrec.ingest.adapters.base as base

    monkeypatch.setattr(base, "no_rewards_confirmed", lambda: {SECURED[:2]})
    c = run_official(*SECURED)
    assert c.value("rewards_program") == "none"
    assert c.fields["base_rate"].null_reason is NullReason.not_applicable
    assert c.fields["reward_currency"].null_reason is NullReason.not_applicable


def test_confirmed_entry_is_ignored_when_the_page_states_earn_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    import bankrec.ingest.adapters.base as base

    monkeypatch.setattr(base, "no_rewards_confirmed", lambda: {UNLIMITED[:2]})
    c = run_official(*UNLIMITED)
    assert "rewards_program" not in c.fields and c.reward_rates
    assert any("no-rewards entry ignored" in n for n in c.notes)


def test_no_rewards_cards_only_for_low_interest_balance_transfer_credit_building() -> None:
    p = card(rewards_program="none", reward_currency=None, base_rate=None, intro_purchase_apr_months=15)
    for goal in ("cashback", "travel"):
        ex = cards.recommend([p], req(goal=goal), NOW).excluded
        assert ex and ex[0].reason.startswith("no rewards program")
    assert cards.recommend([p], req(goal="low_interest"), NOW).results
    assert not any(
        e.reason.startswith("no rewards program")
        for e in cards.recommend([p], req(goal="build_credit"), NOW).excluded
    )
