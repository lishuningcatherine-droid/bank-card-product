"""Auto-approval rule (owner 2026-10-20): only pure additions that pass every check."""

from __future__ import annotations

from typing import Any

from bankrec.db import staging as S
from bankrec.review.auto import summary, why_not

RATE = {"category": "dining", "rate": "3", "rate_unit": "x", "text": "3X on dining"}
BASE = {"category": "other", "rate": "1", "rate_unit": "x", "text": "1X on all other purchases"}


def item(
    changes: list[dict[str, Any]], kind: str = "product", reason: str = "major_change", **ctx: Any
) -> S.ManualReviewItem:
    return S.ManualReviewItem(
        item_kind=kind,
        reason_code=reason,
        context={
            "name": "Example Bank Everyday Cash Card",
            "url": "https://www.examplebank.example/x",
            "changes": changes,
            "conflicts": [],
            "failed_rules": [],
            "missing_key": [],
            **ctx,
        },
    )


def test_pure_additions_are_auto_approvable() -> None:
    it = item(
        [
            {"field": "offer:card_welcome", "old": None, "new": "offer", "rule": "offer_appeared"},
            {"field": "reward_rates", "old": [BASE], "new": [BASE, RATE], "rule": "reward_rates_changed"},
            {"field": "foreign_tx_fee_pct", "old": None, "new": "0", "rule": "default_major"},
        ]
    )
    assert why_not(it) is None
    assert summary(it) == "new card_welcome offer; 1 reward rates added; foreign_tx_fee_pct = 0"


def test_changes_removals_and_failed_checks_wait_for_the_owner() -> None:
    changed_rate = {**BASE, "rate": "2"}
    assert "reward_rates" in str(
        why_not(
            item(
                [
                    {
                        "field": "reward_rates",
                        "old": [BASE],
                        "new": [changed_rate, RATE],
                        "rule": "reward_rates_changed",
                    }
                ]
            )
        )
    )
    assert why_not(
        item([{"field": "reward_rates", "old": [BASE, RATE], "new": [BASE], "rule": "reward_rates_changed"}])
    )
    assert why_not(item([{"field": "annual_fee_cents", "old": 9500, "new": 0, "rule": "default_major"}]))
    assert why_not(item([{"field": "annual_fee_cents", "old": 9500, "new": None, "rule": "default_major"}]))
    assert why_not(
        item([{"field": "offer:card_welcome", "old": None, "new": "offer", "rule": "offer_changed"}])
    )
    add = [{"field": "offer:card_welcome", "old": None, "new": "offer", "rule": "offer_appeared"}]
    assert why_not(item(add, conflicts=[{"field": "x"}])) == "sources conflict"
    assert why_not(item(add, failed_rules=[{"rule": "R-CONF"}])) == "a validation rule failed"
    assert why_not(item(add, missing_key=["base_rate"])) == "a key field is missing"
    assert why_not(item(add, kind="duplicate", reason="fuzzy_match"))
    assert why_not(item(add, kind="offer", reason="offer_needs_review"))
