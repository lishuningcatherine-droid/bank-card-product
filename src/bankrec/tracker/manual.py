"""Hand-entered campaigns (DESIGN §27.8): targeted, branch and referral offers that cannot be captured automatically,
offers from pages that cannot be read reliably, and third-party history. Each entry records who entered it, its
source and when; it stays "pending review" until a reviewer approves it, and only then becomes a campaign.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.tracker import config, deadline, status, terms
from bankrec.tracker.sync import add_version, log_status

Unit = Literal["cash", "statement_credit", "points", "miles", "free_night", "other"]
_ZONES = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}


class TierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(ge=0)
    unit: Unit
    unit_name: str | None = None  # "Membership Rewards points", "Free Night Award"
    spend_cents: int | None = Field(default=None, ge=0)
    window_count: int | None = Field(default=None, gt=0)
    window_unit: Literal["days", "months", "billing_cycles", "statement_periods"] | None = None
    window_start: Literal["account_opening", "approval", "card_membership", "not_stated"] = "not_stated"
    incremental: bool = False
    text: str = Field(min_length=3)


class ComponentIn(BaseModel):
    """A separate, restricted part of a welcome offer (e.g. a travel credit usable only on certain bookings). It is
    never counted as cash and never converted into points or miles; its restriction and expiry stay as stated."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["travel_credit", "restricted_statement_credit", "other"]
    amount_cents: int = Field(gt=0)
    restriction: str = Field(min_length=5, description="what it can be used for, as stated")
    expires: str | None = Field(
        None, description="when it must be used, as stated (e.g. 'first cardholder year')"
    )
    text: str = Field(min_length=10, description="the sentence that states it, verbatim")


class MomentIn(BaseModel):
    """A stated date. A time is kept only when stated, with the zone it was stated in; it is never filled in."""

    model_config = ConfigDict(extra="forbid")
    date: date
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    time_zone: Literal["ET", "CT", "MT", "PT"] | None = None
    text: str = Field(min_length=3, description="the sentence that states the date, verbatim")

    @model_validator(mode="after")
    def _zone_with_time(self) -> MomentIn:
        if self.time is not None and self.time_zone is None:
            raise ValueError("a stated time needs the time zone it was stated in")
        if self.time_zone is not None and self.time is None:
            raise ValueError("time_zone given without a time")
        return self

    def as_moment(self, confirmed: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "date": self.date.isoformat(),
            "time": None,
            "time_known": False,
            "stated_tz": None,
            "stated_date_text": None,
            "text": self.text,
            "confirmed": confirmed,
        }
        if self.time and self.time_zone:
            hh, mm = (int(x) for x in self.time.split(":"))
            local = datetime.combine(self.date, time(hh, mm), tzinfo=ZoneInfo(_ZONES[self.time_zone]))
            et = local.astimezone(deadline.ET)
            out.update(
                date=et.date().isoformat(),
                time=et.strftime("%H:%M"),
                time_known=True,
                stated_tz=self.time_zone,
            )
        return out


class ManualCampaignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_key: str
    channel: Literal["public", "targeted", "referral", "branch"]
    offer_type: Literal["welcome_bonus", "spend_multiplier", "first_year_fee", "first_year_match", "other"]
    tiers: list[TierIn] = Field(min_length=1)
    amount_qualifier: Literal["exact", "up_to", "starting_at", "tiered", "unbounded"] = "exact"
    # for a variable ("as high as") offer: a guaranteed minimum the issuer publishes, with its words
    guaranteed_min: int | None = Field(default=None, ge=0)
    guaranteed_min_text: str | None = None
    offer_components: list[ComponentIn] = Field(default_factory=list)
    annual_fee_cents: int | None = Field(default=None, ge=0)
    first_year_fee_cents: int | None = Field(default=None, ge=0)
    start: MomentIn | None = None
    end: MomentIn | None = None
    eligibility_text: str | None = None
    cap_text: str | None = None
    categories: list[str] = Field(default_factory=list)
    source_kind: Literal["official", "third_party"]
    source_name: str | None = None
    source_url: str
    source_excerpt: str = Field(min_length=10, description="the words the entry rests on, verbatim")
    observed_from: date = Field(description="when the offer was first observed (never the bank's start date)")
    observed_to: date | None = Field(default=None, description="for a past offer: when it was last observed")
    demo: bool = False

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("source_url must be an https URL")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ManualCampaignIn:
        if self.source_kind == "third_party" and not self.source_name:
            raise ValueError("a third-party entry names its source (source_name)")
        if self.card_key not in {c["card_key"] for c in config.cards()} and not self.demo:
            raise ValueError(f"unknown card_key {self.card_key!r} (config/tracker/cards.yaml)")
        if self.amount_qualifier == "tiered" and len(self.tiers) < 2:
            raise ValueError("a tiered offer has at least two tiers")
        if (self.guaranteed_min is None) != (self.guaranteed_min_text is None):
            raise ValueError(
                "a guaranteed minimum needs the words that state it (guaranteed_min_text), and back"
            )
        if self.guaranteed_min is not None and self.amount_qualifier != "up_to":
            raise ValueError("guaranteed_min is only for an up-to (variable) offer")
        if self.observed_to is not None and self.observed_to < self.observed_from:
            raise ValueError("observed_to precedes observed_from")
        if self.demo and not re.search(r"example", self.card_key):
            raise ValueError("demo entries may only use the fictional Example Bank")
        return self

    def to_terms(self) -> dict[str, Any]:
        official = self.source_kind == "official"
        first = self.tiers[0]
        total = sum(t.amount for t in self.tiers) if self.amount_qualifier == "tiered" else first.amount
        return {
            "offer_type": self.offer_type,
            "channel": self.channel,
            "tiers": [t.model_dump() for t in self.tiers],
            "amount_qualifier": self.amount_qualifier,
            "total_amount": total,
            "guaranteed_min": self.guaranteed_min,
            "guaranteed_min_text": terms.norm(self.guaranteed_min_text),
            "offer_components": [c.model_dump() for c in self.offer_components],
            "unit": first.unit,
            "unit_name": first.unit_name,
            "stated_cash_value_cents": None,
            "requirement_type": "spend" if first.spend_cents is not None else None,
            "min_spend_cents": first.spend_cents,
            "window_count": first.window_count,
            "window_unit": first.window_unit,
            "window_start": first.window_start,
            "window_text": None,
            "cap_text": self.cap_text,
            "categories": self.categories,
            "annual_fee_cents": self.annual_fee_cents,
            "first_year_fee_cents": self.first_year_fee_cents,
            "start": self.start.as_moment(official) if self.start else None,
            "end": self.end.as_moment(official) if self.end else deadline.unknown(),
            "eligibility_text": terms.norm(self.eligibility_text),
            "channels_seen": [self.channel],
            "verbatim": terms.norm(self.source_excerpt),
            "offer_url": self.source_url,
        }


def add(session: Session, entry: ManualCampaignIn, *, by: str, now: datetime) -> S.ManualCampaignEntry:
    row = S.ManualCampaignEntry(
        entered_by=by,
        entered_at=now,
        card_key=entry.card_key,
        channel=entry.channel,
        source_kind=entry.source_kind,
        source_name=entry.source_name,
        source_url=entry.source_url,
        source_excerpt=entry.source_excerpt,
        payload=entry.model_dump(mode="json"),
        state="pending_review",
    )
    session.add(row)
    session.flush()
    return row


def amend(
    session: Session, entry_id: int, entry: ManualCampaignIn, *, by: str, reason: str, now: datetime
) -> S.ManualCampaignEntry:
    """Replace the payload of an entry that is still pending review. It stays pending; the previous payload, who
    amended it, when and why are kept in the payload's ``amendments`` list. Approved or rejected entries are final."""
    row = session.get(S.ManualCampaignEntry, entry_id)
    if row is None or row.state != "pending_review":
        raise ValueError(f"entry {entry_id} is not pending review")
    if entry.card_key != row.card_key:
        raise ValueError("an amendment keeps the entry's card")
    history = list((row.payload or {}).get("amendments") or [])
    previous = {k: v for k, v in (row.payload or {}).items() if k != "amendments"}
    history.append({"by": by, "at": now.isoformat(), "reason": reason, "previous": previous})
    row.payload = {**entry.model_dump(mode="json"), "amendments": history}
    row.channel, row.source_kind, row.source_name = entry.channel, entry.source_kind, entry.source_name
    row.source_url, row.source_excerpt = entry.source_url, entry.source_excerpt
    session.flush()
    return row


def pending(session: Session) -> list[S.ManualCampaignEntry]:
    return list(
        session.scalars(
            select(S.ManualCampaignEntry)
            .where(S.ManualCampaignEntry.state == "pending_review")
            .order_by(S.ManualCampaignEntry.id)
        )
    )


def approve(session: Session, entry_id: int, *, reviewer: str, now: datetime) -> P.Campaign:
    row = session.get(S.ManualCampaignEntry, entry_id)
    if row is None or row.state != "pending_review":
        raise ValueError(f"entry {entry_id} is not pending review")
    if row.entered_by == reviewer:
        raise ValueError("an entry is approved by someone other than the person who entered it")
    entry = ManualCampaignIn.model_validate({k: v for k, v in row.payload.items() if k != "amendments"})
    card = session.get(P.TrackedCard, entry.card_key)
    if card is None:
        raise ValueError(f"card {entry.card_key} is not synced yet (run `bankrec offers sync`)")
    t = entry.to_terms()
    observed = datetime.combine(entry.observed_from, time(12), tzinfo=UTC)
    if entry.observed_to is None:
        # the same current offer already tracked (same card, channel, type and reward structure): the review
        # verifies it — or adds a version when a term differs — instead of creating a duplicate (owner 2026-11-11)
        existing = same_offer(session, entry.card_key, t)
        if existing is not None:
            verify_existing(session, existing, entry, t, entry_id=row.id, entered_by=row.entered_by,
                            reviewer=reviewer, now=now)  # fmt: skip
            row.state, row.reviewed_by, row.reviewed_at = "approved", reviewer, now
            row.campaign_id = str(existing.id)
            session.flush()
            return existing
    c = P.Campaign(
        campaign_key=f"{terms.campaign_key(entry.card_key, t)}|m{row.id}",
        card_key=entry.card_key,
        channel=entry.channel,
        offer_type=entry.offer_type,
        structure=terms.structure(t),
        status="active",
        # an official source entered by hand is "manual"; it is not re-checked automatically
        source_kind="manual" if entry.source_kind == "official" else "third_party",
        officially_verified=entry.source_kind == "official",
        source_name=entry.source_name,
        first_seen_at=observed,
        last_checked_at=now,
        last_verified_at=observed if entry.observed_to is None else None,
        consecutive_failures=0,
        prod_offer_ids=[],
        demo=entry.demo or card.demo,
    )
    session.add(c)
    session.flush()
    v = add_version(session, c, t, observed, url=entry.source_url, excerpt=entry.source_excerpt, changes=[])
    if entry.observed_to is not None:
        v.valid_to = datetime.combine(entry.observed_to, time(12), tzinfo=UTC)
        c.status = None  # type: ignore[assignment]
        log_status(
            session,
            c,
            "expired",
            f"past offer entered as history and approved by {reviewer}",
            now,
            trigger="manual",
            actor=reviewer,
        )
    else:
        c.status = None  # type: ignore[assignment]
        st, why = status.compute(
            None,
            end=t.get("end"),
            now=now,
            last_verified_at=None,  # hand-entered: not re-checked automatically, so never "stale" by age
            consecutive_failures=0,
            not_seen=False,
        )
        log_status(
            session,
            c,
            st,
            f"manual entry {row.id} approved by {reviewer}; {reason_for(st, why, entry)}",
            now,
            trigger="manual",
            actor=reviewer,
        )
    session.add(
        P.CampaignCheck(
            campaign_id=c.id,
            at=now,
            outcome="manual",
            detail=f"entered by {row.entered_by} on {row.entered_at.date()}, approved by {reviewer}",
        )
    )
    row.state, row.reviewed_by, row.reviewed_at, row.campaign_id = "approved", reviewer, now, str(c.id)
    session.flush()
    return c


def same_offer(session: Session, card_key: str, t: dict[str, Any]) -> P.Campaign | None:
    """The current campaign with this offer's identity, if any (expired or withdrawn ones are history)."""
    return session.scalar(
        select(P.Campaign).where(
            P.Campaign.campaign_key == terms.campaign_key(card_key, t),
            P.Campaign.status.not_in(tuple(status.FINAL)),
        )
    )


def verify_existing(
    session: Session,
    c: P.Campaign,
    entry: ManualCampaignIn,
    t: dict[str, Any],
    *,
    entry_id: int,
    entered_by: str,
    reviewer: str,
    now: datetime,
) -> bool:
    """Record a reviewed manual entry on the campaign it describes. Same terms → a verification only; a material
    difference → a new version (the old one kept). Returns whether a version was added."""
    observed = datetime.combine(entry.observed_from, time(12), tzinfo=UTC)
    latest = max(c.versions, key=lambda v: v.version)
    changed = terms.material_hash(t) != terms.material_hash(latest.terms)
    detail = f"manual entry {entry_id}: entered by {entered_by}, approved by {reviewer}; source read {entry.observed_from}"
    if changed:
        changes = terms.diff(latest.terms, t)
        add_version(session, c, t, max(observed, latest.valid_from), url=entry.source_url,
                    excerpt=entry.source_excerpt, changes=changes)  # fmt: skip
        detail += "; new version: " + ", ".join(ch["field"] for ch in changes)
    else:
        detail += "; same terms"
    session.add(P.CampaignCheck(campaign_id=c.id, at=now, outcome="manual", detail=detail))
    official = entry.source_kind == "official"
    if official:
        c.officially_verified = True
        if c.last_verified_at is None or observed > c.last_verified_at:
            c.last_verified_at, c.consecutive_failures = observed, 0
    st, why = status.compute(
        c.status,
        end=t.get("end"),
        now=now,
        last_verified_at=c.last_verified_at if c.source_kind == "official" else None,
        consecutive_failures=c.consecutive_failures,
        not_seen=False,
    )
    if st != c.status:
        log_status(session, c, st, f"manual entry {entry_id} approved by {reviewer}; {reason_for(st, why, entry)}", now,
                   trigger="manual", actor=reviewer)  # fmt: skip
    session.flush()
    return changed


MANUAL_ACTIVE_REASON = (
    "terms verified by hand against the {kind} page read {day} (not confirmed by automatic reading)"
)


def reason_for(st: str, why: str, entry: ManualCampaignIn) -> str:
    """The status reason after a manual verification: an "active" status rests on the reviewer's check of the page,
    never on an automatic reading (whose reason text says "shown on the official page at the last successful check")."""
    if st == "active":
        kind = "official" if entry.source_kind == "official" else "third-party"
        return MANUAL_ACTIVE_REASON.format(kind=kind, day=entry.observed_from)
    return why


def merge_duplicates(session: Session, *, now: datetime, apply: bool) -> list[str]:
    """Campaigns created from approved manual entries while the same current offer was already tracked: fold each
    into that campaign (a verification, or a new version) and remove the duplicate. Dry run unless ``apply``."""
    done: list[str] = []
    rows = session.scalars(
        select(S.ManualCampaignEntry).where(
            S.ManualCampaignEntry.state == "approved", S.ManualCampaignEntry.campaign_id.is_not(None)
        )
    )
    for row in rows:
        dup = session.get(P.Campaign, row.campaign_id)
        if dup is None or "|m" not in dup.campaign_key or dup.status in status.FINAL:
            continue
        entry = ManualCampaignIn.model_validate({k: v for k, v in row.payload.items() if k != "amendments"})
        if entry.observed_to is not None:
            continue
        t = entry.to_terms()
        target = same_offer(session, entry.card_key, t)
        if target is None or target.id == dup.id:
            continue
        latest = max(target.versions, key=lambda v: v.version)
        what = (
            "new version" if terms.material_hash(t) != terms.material_hash(latest.terms) else "verification"
        )
        done.append(f"entry {row.id} ({entry.card_key}): merge into the existing campaign as a {what}")
        if apply:
            verify_existing(session, target, entry, t, entry_id=row.id, entered_by=row.entered_by,
                            reviewer=row.reviewed_by or "owner", now=now)  # fmt: skip
            row.campaign_id = str(target.id)
            session.delete(dup)
            session.flush()
    return done


def reject(session: Session, entry_id: int, *, reviewer: str, note: str, now: datetime) -> None:
    row = session.get(S.ManualCampaignEntry, entry_id)
    if row is None or row.state != "pending_review":
        raise ValueError(f"entry {entry_id} is not pending review")
    row.state, row.reviewed_by, row.reviewed_at, row.review_note = "rejected", reviewer, now, note


def set_status(
    session: Session, campaign_id: str, new: str, *, reviewer: str, reason: str, now: datetime
) -> None:
    """A reviewer's status decision (e.g. withdrawn after confirming with the bank); always logged."""
    if new not in status.STATUSES:
        raise ValueError(f"unknown status {new!r}")
    c = session.get(P.Campaign, campaign_id)
    if c is None:
        raise ValueError(f"no campaign {campaign_id}")
    log_status(session, c, new, reason, now, trigger="manual", actor=reviewer)
