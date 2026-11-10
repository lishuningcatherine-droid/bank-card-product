"""Tracker update flow on PostgreSQL with the fictional Example Bank (DESIGN §27.7). Acceptance items: several
campaigns per card, old terms kept after an update, page noise creates no duplicate, failed checks never end a
campaign, manual entries wait for review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.tracker import config, manual
from bankrec.tracker.sync import sync

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)
CARD = {"card_key": "example_bank:everyday-cash", "bank_id": "example_bank",
        "canonical_key": "example_bank:credit_card:consumer:example bank everyday cash:-",
        "source_ids": ["example_bank:everyday-cash"], "series": "Everyday", "points_program": None}  # fmt: skip


@pytest.fixture(autouse=True)
def _example_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "cards", lambda: [CARD])


def _product(session) -> P.Product:  # type: ignore[no-untyped-def]
    session.add(P.Bank(bank_id="example_bank", display_name="Example Bank", official_domains=["examplebank.example"],
                       product_type_availability={}, test_only=True, known_limitations=[]))  # fmt: skip
    p = P.Product(
        canonical_key=CARD["canonical_key"], bank_id="example_bank", product_type="credit_card",
        official_name="Example Bank Everyday Cash Card", official_url="https://www.examplebank.example/cards/everyday",
        retrieved_at=T0, verified_at=T0, first_published_at=T0, last_confirmed_at=T0, last_checked_at=T0,
        test_only=True,
    )  # fmt: skip
    p.card = P.CreditCardDetails(segment="consumer", annual_fee_cents=0)
    session.add(p)
    session.flush()
    return p


def _offer(session, p: P.Product, *, amount: int = 20000, audience: str = "public", at: datetime = T0,
           text: str | None = None, spend: int = 50000) -> P.Offer:  # fmt: skip
    o = P.Offer(
        offer_key=uuid.uuid4().hex[:20], product_id=p.id, offer_type="card_welcome", reward_unit="cents",
        amount_qualifier="exact", amount_min=amount, amount_max=amount, requirement_type="spend",
        requirement_qualifier="exact", requirement_min_cents=spend, requirement_max_cents=spend,
        qualification_window_count=3, qualification_window_unit="months",
        qualification_window_text="in the first 3 months from account opening", audience=audience,
        offer_url="https://www.examplebank.example/cards/everyday",
        verbatim_text=text or f"Earn a ${amount // 100} bonus after you spend ${spend // 100} on purchases in the first 3 months from account opening.",
        retrieved_at=at, verified_at=at, last_confirmed_at=at, status="current", seen_on=[],
    )  # fmt: skip
    session.add(o)
    session.flush()
    return o


def _run(session, at: datetime, status: str, failure: str | None = None) -> None:  # type: ignore[no-untyped-def]
    session.add(S.RunSourceStatus(run_id=f"r{at:%m%d%H%M}", source_id="example_bank:everyday-cash",
                                  terminal_status=status, failure=failure, at=at))  # fmt: skip
    session.flush()


def _campaigns(session) -> list[P.Campaign]:  # type: ignore[no-untyped-def]
    return list(session.scalars(select(P.Campaign).order_by(P.Campaign.campaign_key)))


def test_one_card_keeps_several_channels_and_times(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    _offer(session, p, amount=20000)
    _offer(session, p, amount=30000, audience="targeted")
    sync(session, T0)
    cs = _campaigns(session)
    assert {c.channel for c in cs} == {"public", "targeted"}
    assert all(c.card_key == CARD["card_key"] for c in cs)


def test_update_keeps_old_terms_and_history(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    old = _offer(session, p, amount=20000)
    sync(session, T0)
    # the bank raises the bonus: the pipeline retires the old offer and publishes the new one
    old.status = "recheck_pending"
    t1 = T0 + timedelta(days=3)
    _offer(session, p, amount=25000, at=t1)
    _run(session, t1, "published")
    sync(session, t1)
    [c] = _campaigns(session)
    assert [v.version for v in c.versions] == [1, 2]
    v1, v2 = c.versions
    assert v1.terms["total_amount"] == 20000 and v1.valid_to == t1  # the old terms stay readable
    assert v2.terms["total_amount"] == 25000 and v2.valid_to is None
    assert {ch["field"] for ch in v2.change_summary} >= {"total_amount", "tiers"}
    assert c.status == "active"


def test_page_noise_creates_no_duplicate_campaign(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    o = _offer(session, p)
    sync(session, T0)
    t1 = T0 + timedelta(days=1)
    o.verbatim_text = "NEW LAYOUT — Earn a $200 bonus after you spend $500 on purchases in the first 3 months from account opening."
    o.last_confirmed_at = t1
    _run(session, t1, "published")
    sync(session, t1)
    [c] = _campaigns(session)
    assert len(c.versions) == 1
    assert c.last_verified_at == t1  # only the verification time moved
    outcomes = [k.outcome for k in session.scalars(select(P.CampaignCheck).order_by(P.CampaignCheck.at))]
    assert outcomes == ["seen", "seen"]


def test_failed_checks_never_end_a_campaign(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    t = T0
    for i in range(3):
        t = T0 + timedelta(hours=6 * (i + 1))
        _run(session, t, "retrieval_failed", "TIMEOUT")
        sync(session, t)
        [c] = _campaigns(session)
        assert c.status == ("active" if i < 2 else "stale")
    assert c.status != "expired" and c.consecutive_failures == 3
    log = list(session.scalars(select(P.CampaignStatusLog).order_by(P.CampaignStatusLog.at)))
    assert [(x.from_status, x.to_status, x.trigger) for x in log] == [
        (None, "active", "auto"),
        ("active", "stale", "auto"),
    ]
    assert "not treated as ended" in log[-1].reason


def test_offer_missing_from_a_good_capture_needs_verification(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    o = _offer(session, p)
    sync(session, T0)
    o.status = "recheck_pending"  # pipeline: offer_disappeared
    t1 = T0 + timedelta(days=1)
    _run(session, t1, "published")
    sync(session, t1)
    [c] = _campaigns(session)
    assert c.status == "pending_verification"
    assert c.versions[-1].valid_to is None  # terms kept, not deleted


def test_manual_entry_waits_for_review(session) -> None:  # type: ignore[no-untyped-def]
    _product(session)
    sync(session, T0)
    entry = manual.ManualCampaignIn.model_validate(
        {
            "card_key": CARD["card_key"], "channel": "branch", "offer_type": "welcome_bonus",
            "tiers": [{"amount": 30000, "unit": "cash", "spend_cents": 100000, "window_count": 90,
                       "window_unit": "days", "window_start": "account_opening",
                       "text": "Get $300 after $1,000 in 90 days (branch flyer)"}],
            "end": {"date": "2026-12-05", "text": "Offer ends December 5, 2026."},
            "source_kind": "official", "source_url": "https://www.examplebank.example/branch-offer",
            "source_excerpt": "Get $300 after $1,000 in 90 days. Offer ends December 5, 2026.",
            "observed_from": "2026-11-01", "demo": True,
        }
    )  # fmt: skip
    row = manual.add(session, entry, by="alice", now=T0)
    assert row.state == "pending_review" and _campaigns(session) == []
    with pytest.raises(ValueError, match="someone other"):
        manual.approve(session, row.id, reviewer="alice", now=T0)
    c = manual.approve(session, row.id, reviewer="bob", now=T0)
    assert c.channel == "branch" and c.source_kind == "manual" and c.demo
    assert c.versions[0].terms["end"]["time"] is None  # no time stated → none invented
    assert row.state == "approved" and row.reviewed_by == "bob"


def test_manual_time_needs_its_zone() -> None:
    with pytest.raises(ValueError, match="time zone"):
        manual.MomentIn.model_validate(
            {"date": "2026-12-05", "time": "23:59", "text": "Apply by 12/5 11:59pm"}
        )
