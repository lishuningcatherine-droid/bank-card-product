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


def test_stale_stored_hash_creates_no_version(session) -> None:  # type: ignore[no-untyped-def]
    """Regression (2026-11-10): a hash stored under an older definition of the material fields must not make a
    version when the terms are materially the same; the stored hash is refreshed instead."""
    p = _product(session)
    o = _offer(session, p)
    sync(session, T0)
    [c] = _campaigns(session)
    [v] = c.versions
    v.material_hash = "0" * 40  # as written by an older definition
    o.offer_url = "https://www.examplebank.example/cards/everyday?tracking=1"  # not a material term
    t1 = T0 + timedelta(days=1)
    o.last_confirmed_at = t1
    _run(session, t1, "published")
    sync(session, t1)
    [c] = _campaigns(session)
    assert len(c.versions) == 1 and c.versions[0].material_hash != "0" * 40


def _counts(session) -> dict[str, int]:  # type: ignore[no-untyped-def]
    from sqlalchemy import func

    return {
        m.__tablename__: session.scalar(select(func.count()).select_from(m))
        for m in (
            P.Campaign,
            P.CampaignVersion,
            P.CampaignStatusLog,
            P.CampaignCheck,
            P.ApplicationRule,
            P.TrackedCard,
        )
    }


def test_repeated_sync_of_unchanged_offers_is_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    """Owner requirement 2026-11-10: syncing the same published offers again changes nothing — no campaign, version,
    status entry or check is added, and the stored terms and hashes stay as they are."""
    p = _product(session)
    _offer(session, p, amount=20000)
    _offer(session, p, amount=30000, audience="targeted")
    first = sync(session, T0)
    assert len(first.new_campaigns) == 2
    before = _counts(session)
    hashes = {v.id: (v.material_hash, v.terms, v.valid_to) for c in _campaigns(session) for v in c.versions}
    for hours in (1, 2, 24):  # later runs of the same unchanged state, with no new page captures
        again = sync(session, T0 + timedelta(hours=hours))
        assert again.new_campaigns == [] and again.new_versions == [] and again.status_changes == []
    assert _counts(session) == before
    assert {
        v.id: (v.material_hash, v.terms, v.valid_to) for c in _campaigns(session) for v in c.versions
    } == hashes


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
    [log] = session.scalars(select(P.CampaignStatusLog).where(P.CampaignStatusLog.campaign_id == c.id))
    assert "verified by hand" in log.reason and "last successful check" not in log.reason
    assert c.versions[0].terms["end"]["time"] is None  # no time stated → none invented
    assert row.state == "approved" and row.reviewed_by == "bob"


def test_amending_a_pending_entry_keeps_it_pending_and_keeps_the_previous_payload(session) -> None:  # type: ignore[no-untyped-def]
    _product(session)
    sync(session, T0)
    data = {
        "card_key": CARD["card_key"], "channel": "public", "offer_type": "welcome_bonus",
        "tiers": [{"amount": 30000, "unit": "cash", "spend_cents": 100000, "window_count": 3,
                   "window_unit": "months", "window_start": "account_opening",
                   "text": "Get $300 after $1,000 in 3 months"}],
        "source_kind": "official", "source_url": "https://www.examplebank.example/offer",
        "source_excerpt": "Get $300 after $1,000 in 3 months.", "observed_from": "2026-11-01", "demo": True,
    }  # fmt: skip
    row = manual.add(session, manual.ManualCampaignIn.model_validate(data), by="alice", now=T0)
    fixed = {**data, "offer_components": [{"kind": "travel_credit", "amount_cents": 10000,
                                     "restriction": "hotel bookings through Example Travel",
                                     "expires": "in your first cardholder year",
                                     "text": "Plus $100 for hotel bookings through Example Travel"}]}  # fmt: skip
    manual.amend(session, row.id, manual.ManualCampaignIn.model_validate(fixed), by="alice", reason="add the credit",
                 now=T0)  # fmt: skip
    assert row.state == "pending_review"
    [a] = row.payload["amendments"]
    assert a["by"] == "alice" and a["reason"] == "add the credit" and a["previous"]["offer_components"] == []
    c = manual.approve(session, row.id, reviewer="bob", now=T0)
    assert c.versions[0].terms["offer_components"][0]["amount_cents"] == 10000
    with pytest.raises(ValueError, match="not pending"):
        manual.amend(
            session, row.id, manual.ManualCampaignIn.model_validate(data), by="alice", reason="x", now=T0
        )


def test_rule_removed_from_config_is_retired(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _product(session)
    sync(session, T0)
    assert session.get(P.ApplicationRule, "chase_5_24") is not None
    kept = [r for r in config.rules() if r["rule_key"] != "chase_5_24"]
    monkeypatch.setattr(config, "rules", lambda: kept)
    rep = sync(session, T0 + timedelta(hours=1))
    assert rep.rules_retired == ["chase_5_24"]
    assert session.get(P.ApplicationRule, "chase_5_24") is None


def _same_as_offer(**extra) -> manual.ManualCampaignIn:  # type: ignore[no-untyped-def]
    """A hand entry of the offer `_offer` publishes (same terms), as a reviewer would enter it."""
    return manual.ManualCampaignIn.model_validate({
        "card_key": CARD["card_key"], "channel": "public", "offer_type": "welcome_bonus",
        "tiers": [{"amount": 20000, "unit": "cash", "unit_name": None, "spend_cents": 50000, "window_count": 3,
                   "window_unit": "months", "window_start": "account_opening",
                   "text": "Earn a $200 bonus after you spend $500 on purchases in the first 3 months from account opening."}],
        "annual_fee_cents": 0, "first_year_fee_cents": 0,
        "source_kind": "official", "source_url": "https://www.examplebank.example/cards/everyday",
        "source_excerpt": "Earn a $200 bonus after you spend $500", "observed_from": "2026-11-02", "demo": True, **extra,
    })  # fmt: skip


def test_approving_an_entry_for_a_tracked_offer_verifies_it_instead_of_duplicating(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    [official] = _campaigns(session)
    row = manual.add(session, _same_as_offer(), by="claude", now=T0)
    c = manual.approve(session, row.id, reviewer="owner", now=T0 + timedelta(days=2))
    assert c.id == official.id and len(_campaigns(session)) == 1
    assert len(c.versions) == 1  # same terms: a verification only
    assert row.state == "approved" and row.campaign_id == str(c.id)
    checks = [k for k in session.scalars(select(P.CampaignCheck).where(P.CampaignCheck.campaign_id == c.id))]
    assert any(k.outcome == "manual" and "same terms" in (k.detail or "") for k in checks)
    # a reviewed entry with an extra restricted credit adds a version to the same campaign, keeping the old one
    extra = {"offer_components": [{"kind": "travel_credit", "amount_cents": 10000, "restriction": "hotel bookings",
                                   "expires": None, "text": "Plus $100 for hotel bookings"}]}  # fmt: skip
    row2 = manual.add(session, _same_as_offer(**extra), by="claude", now=T0)
    c2 = manual.approve(session, row2.id, reviewer="owner", now=T0 + timedelta(days=3))
    assert c2.id == official.id and [v.version for v in c2.versions] == [1, 2]
    assert (
        c2.versions[0].valid_to is not None
        and c2.versions[1].change_summary[0]["field"] == "offer_components"
    )


def test_existing_duplicates_are_merged(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    [official] = _campaigns(session)
    row = manual.add(session, _same_as_offer(), by="claude", now=T0)
    monkeypatch.setattr(
        manual, "same_offer", lambda *a, **k: None
    )  # the old approval path: always a new campaign
    manual.approve(session, row.id, reviewer="owner", now=T0)
    monkeypatch.undo()
    assert len(_campaigns(session)) == 2
    plan = manual.merge_duplicates(session, now=T0 + timedelta(days=1), apply=False)
    assert (
        len(plan) == 1 and "verification" in plan[0] and len(_campaigns(session)) == 2
    )  # dry run changes nothing
    manual.merge_duplicates(session, now=T0 + timedelta(days=1), apply=True)
    [c] = _campaigns(session)
    assert c.id == official.id and row.campaign_id == str(c.id) and len(c.versions) == 1
    assert manual.merge_duplicates(session, now=T0 + timedelta(days=1), apply=True) == []


def test_manual_time_needs_its_zone() -> None:
    with pytest.raises(ValueError, match="time zone"):
        manual.MomentIn.model_validate(
            {"date": "2026-12-05", "time": "23:59", "text": "Apply by 12/5 11:59pm"}
        )


def test_a_version_that_keeps_the_amount_is_one_history_record(session) -> None:  # type: ignore[no-untyped-def]
    from bankrec.tracker import views as TV

    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    extra = {"eligibility_text": "Not available if you have had this card."}  # a material change, same amount
    row = manual.add(session, _same_as_offer(**extra), by="claude", now=T0)
    c = manual.approve(session, row.id, reviewer="owner", now=T0 + timedelta(days=2))
    assert [v.version for v in c.versions] == [1, 2]
    recs = TV.Builder(session, allow_demo=True).records(CARD["card_key"], "cash", c)
    assert len(recs) == 1 and recs[0].current and recs[0].valid_from == c.versions[0].valid_from


def _tier(**over):  # type: ignore[no-untyped-def]
    t = {"amount": 20000, "unit": "cash", "spend_cents": 50000, "window_count": 3, "window_unit": "months",
         "window_start": "account_opening",
         "text": "Earn a $200 bonus after you spend $500 on purchases in the first 3 months from account opening."}  # fmt: skip
    return [{**t, **over}]


@pytest.mark.parametrize(
    "change,records",
    [
        ({}, 1),  # only the eligibility wording changed: one record
        ({"spend_cents": 100000}, 2),  # same amount, higher spend: a different offer level
        ({"window_count": 6}, 2),  # same amount and spend, longer window
        ({"window_unit": "days", "window_count": 90}, 2),
    ],
)
def test_history_merges_versions_only_when_amount_spend_and_window_are_unchanged(
    session, change, records
) -> None:  # type: ignore[no-untyped-def]
    from bankrec.tracker import views as TV

    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    extra = {"tiers": _tier(**change), "eligibility_text": "Not available if you have had this card."}
    row = manual.add(session, _same_as_offer(**extra), by="claude", now=T0)
    c = manual.approve(session, row.id, reviewer="owner", now=T0 + timedelta(days=2))
    assert [v.version for v in c.versions] == [1, 2]
    recs = TV.Builder(session, allow_demo=True).records(CARD["card_key"], "cash", c)
    assert len(recs) == records
    assert recs[-1].current


def test_manual_verification_says_so_in_the_status_log(session) -> None:  # type: ignore[no-untyped-def]
    p = _product(session)
    _offer(session, p)
    sync(session, T0)
    [c] = _campaigns(session)
    c.status = "pending_verification"  # the page was captured but the reader no longer found the offer
    row = manual.add(session, _same_as_offer(), by="claude", now=T0)
    manual.approve(session, row.id, reviewer="owner", now=T0 + timedelta(days=2))
    last = session.scalars(
        select(P.CampaignStatusLog)
        .where(P.CampaignStatusLog.campaign_id == c.id)
        .order_by(P.CampaignStatusLog.at.desc())
    ).first()
    assert last.to_status == "active" and last.trigger == "manual" and last.actor == "owner"
    assert "verified by hand against the official page read 2026-11-02" in last.reason
    assert "last successful check" not in last.reason


def test_terms_the_automatic_reading_did_not_capture_are_kept_not_removed(session) -> None:  # type: ignore[no-untyped-def]
    """The Neon test-branch run of 2026-11-12: a hand-verified eligibility clause (Chase Sapphire v2) and the page
    read again, unchanged, by the automatic reader, which does not capture that clause. Sync made a v3 'removing'
    it. An empty value from the automatic reading means "not captured", so no version (DESIGN §27.14)."""
    p = _product(session)
    o = _offer(session, p)
    sync(session, T0)
    clause = "This card is unavailable to you if you currently have this card open."
    extra = {
        "eligibility_text": clause,
        "offer_components": [{"kind": "travel_credit", "amount_cents": 10000, "restriction": "hotel bookings",
                              "expires": None, "text": "Plus $100 for hotel bookings"}],
    }  # fmt: skip
    row = manual.add(session, _same_as_offer(**extra), by="claude", now=T0)
    [c] = [manual.approve(session, row.id, reviewer="owner", now=T0 + timedelta(days=1))]
    assert [v.version for v in c.versions] == [1, 2]
    before = _counts(session)
    for day in (2, 3):  # the page is read again (unchanged) and synced, twice
        o.last_confirmed_at = o.verified_at = T0 + timedelta(days=day)
        _run(session, T0 + timedelta(days=day), "unchanged")
        report = sync(session, T0 + timedelta(days=day))
        assert report.new_versions == []
    assert [v.version for v in c.versions] == [1, 2]
    assert _counts(session)["campaign_versions"] == before["campaign_versions"]
    latest = c.versions[-1].terms
    assert latest["eligibility_text"] == clause
    assert latest["offer_components"][0]["amount_cents"] == 10000

    # a real change on the page still makes a version, which keeps the hand-verified terms it did not contradict
    o.amount_min = o.amount_max = 30000
    o.verbatim_text = (
        "Earn a $300 bonus after you spend $500 on purchases in the first 3 months from account opening."
    )
    report = sync(session, T0 + timedelta(days=4))
    assert [v.version for v in c.versions] == [1, 2, 3]
    v3 = c.versions[-1]
    assert [ch["field"] for ch in v3.change_summary] == ["tiers", "total_amount"]
    assert (
        v3.terms["eligibility_text"] == clause
        and v3.terms["offer_components"][0]["restriction"] == "hotel bookings"
    )
    assert v3.terms["kept_from_previous"] == ["eligibility_text", "offer_components"]

    # wording the automatic reading does capture, and that differs, is a change
    o.eligibility_restrictions = "This card is not available to current cardmembers."
    report = sync(session, T0 + timedelta(days=5))
    assert [ch["field"] for ch in c.versions[-1].change_summary] == ["eligibility_text"]
    assert report.new_versions and c.versions[-1].terms["eligibility_text"].startswith(
        "This card is not available"
    )
