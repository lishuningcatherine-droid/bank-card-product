"""The tracker's update step (DESIGN §27.7): published offers → campaigns, versions, checks and statuses.

Runs after each pipeline run (``bankrec offers update`` runs both). It never deletes: a campaign that disappears is
marked for verification, a failed check only counts a failure, and history keeps every version.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.tracker import config, status, terms

log = logging.getLogger("bankrec.tracker")
SUCCESS = {"published", "unchanged"}
_SEEN_SLACK = timedelta(minutes=30)


@dataclass
class SyncReport:
    cards_linked: int = 0
    cards_missing: list[str] = field(default_factory=list)
    new_campaigns: list[str] = field(default_factory=list)
    new_versions: list[str] = field(default_factory=list)
    status_changes: list[str] = field(default_factory=list)
    checks: dict[str, int] = field(default_factory=dict)
    rules: int = 0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def sync_cards(session: Session, report: SyncReport) -> dict[str, P.TrackedCard]:
    out: dict[str, P.TrackedCard] = {}
    for spec in config.cards():
        product = session.scalar(select(P.Product).where(P.Product.canonical_key == spec["canonical_key"]))
        row = session.get(P.TrackedCard, spec["card_key"]) or P.TrackedCard(card_key=spec["card_key"])
        row.bank_id, row.canonical_key = spec["bank_id"], spec["canonical_key"]
        row.series, row.points_program = spec.get("series"), spec.get("points_program")
        row.source_ids = list(spec.get("source_ids", []))
        row.reports_to_personal_credit = _jsonable(spec.get("reports_to_personal_credit"))
        row.counts_toward_chase_524 = _jsonable(spec.get("counts_toward_chase_524"))
        if product is not None and product.status == "published":
            row.product_id, row.official_name = product.id, product.official_name
            row.official_url = product.official_url
            row.segment = product.card.segment if product.card else "consumer"
            row.demo = product.test_only
            report.cards_linked += 1
        else:
            report.cards_missing.append(spec["card_key"])
            row.product_id = None
            row.official_name = row.official_name or spec["card_key"]
            row.segment = row.segment or ("business" if ":business:" in spec["canonical_key"] else "consumer")
        session.add(row)
        out[row.card_key] = row
    session.flush()
    return out


def _jsonable(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}


def sync_rules(session: Session, report: SyncReport) -> None:
    for r in config.rules():
        row = session.get(P.ApplicationRule, r["rule_key"]) or P.ApplicationRule(rule_key=r["rule_key"])
        row.bank_id, row.name, row.rule_type = r["bank_id"], r["name"], r["rule_type"]
        row.source_type, row.verification = r["source_type"], r["verification"]
        row.effect, row.strength, row.test = r["effect"], r["strength"], r["test"]
        row.window_months, row.limit_count, row.counts = (
            r.get("window_months"),
            r.get("limit"),
            r.get("counts"),
        )
        row.scope = {
            "match": r.get("match", {}),
            "applies_to": r.get("applies_to", {}),
            "windows": r.get("windows"),
            "also_bonus_received": bool(r.get("also_bonus_received")),
            "also_current_holder": bool(r.get("also_current_holder")),
            "source_id": r.get("source_id"),
        }
        row.source_url, row.source_title = r["source_url"], r.get("source_title")
        row.excerpt, row.notes = r["excerpt"], list(r.get("notes", []))
        row.verified_at = _date(r["verified_at"]) or date.today()
        session.add(row)
        report.rules += 1
    session.flush()


def log_status(
    session: Session,
    c: P.Campaign,
    new: str,
    reason: str,
    now: datetime,
    *,
    trigger: str = "auto",
    actor: str | None = None,
) -> None:
    session.add(
        P.CampaignStatusLog(
            campaign_id=c.id,
            at=now,
            from_status=c.status if c.id and c.status else None,
            to_status=new,
            reason=reason,
            trigger=trigger,
            actor=actor,
        )
    )
    c.status, c.status_reason = new, reason


def add_version(
    session: Session,
    c: P.Campaign,
    t: dict[str, Any],
    now: datetime,
    *,
    url: str | None,
    excerpt: str | None,
    changes: list[dict[str, Any]],
) -> P.CampaignVersion:
    for v in c.versions:
        if v.valid_to is None:
            v.valid_to = now
    n = max((v.version for v in c.versions), default=0) + 1
    v = P.CampaignVersion(
        version=n,
        material_hash=terms.material_hash(t),
        terms=t,
        change_summary=changes,
        source_url=url,
        source_excerpt=excerpt,
        valid_from=now,
        **terms.filter_columns(t),
    )
    c.versions.append(v)
    c.current_version = n
    return v


def _latest(c: P.Campaign) -> P.CampaignVersion:
    return max(c.versions, key=lambda v: v.version)


def _check(
    session: Session,
    c: P.Campaign,
    at: datetime,
    outcome: str,
    report: SyncReport,
    *,
    run_id: str | None = None,
    source_id: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        P.CampaignCheck(
            campaign_id=c.id, at=at, run_id=run_id, source_id=source_id, outcome=outcome, detail=detail
        )
    )
    report.checks[outcome] = report.checks.get(outcome, 0) + 1


def _runs_since(session: Session, source_ids: list[str], since: datetime | None) -> list[S.RunSourceStatus]:
    q = select(S.RunSourceStatus).where(S.RunSourceStatus.source_id.in_(source_ids))
    if since is not None:
        q = q.where(S.RunSourceStatus.at > since)
    return list(session.scalars(q.order_by(S.RunSourceStatus.at)))


def sync_campaigns(session: Session, card: P.TrackedCard, now: datetime, report: SyncReport) -> None:
    if card.product_id is None:
        return
    product = session.get(P.Product, card.product_id)
    assert product is not None
    offers = list(session.scalars(select(P.Offer).where(P.Offer.product_id == product.id)))
    existing = {
        c.campaign_key: c
        for c in session.scalars(select(P.Campaign).where(P.Campaign.card_key == card.card_key))
    }
    current: dict[str, tuple[P.Offer, dict[str, Any]]] = {}
    for o in sorted(offers, key=lambda o: str(o.id)):
        if o.status != "current":
            continue
        t = terms.from_offer(o, product)
        key = terms.campaign_key(card.card_key, t)
        if key in current and terms.material_hash(current[key][1]) != terms.material_hash(t):
            # two different offers of the same structure at once (e.g. two pages): kept apart by their page
            key = f"{key}|{hashlib.sha1(o.offer_url.encode()).hexdigest()[:8]}"  # noqa: S324
        current[key] = (o, t)

    for key, (o, t) in current.items():
        c = existing.get(key)
        url, excerpt = t["offer_url"], t.get("verbatim")
        if c is None:
            c = P.Campaign(
                campaign_key=key,
                card_key=card.card_key,
                channel=t["channel"],
                offer_type=t["offer_type"],
                structure=terms.structure(t),
                status="active",
                source_kind="official",
                officially_verified=True,
                first_seen_at=o.verified_at if o.verified_at < now else now,
                consecutive_failures=0,
                last_verified_at=o.last_confirmed_at,
                last_checked_at=now,
                prod_offer_ids=[str(o.id)],
                demo=card.demo,
            )
            session.add(c)
            session.flush()
            add_version(session, c, t, now, url=url, excerpt=excerpt, changes=[])
            c.status = None  # type: ignore[assignment]  # first log entry has no previous status
            st, why = status.compute(
                None,
                end=t.get("end"),
                now=now,
                last_verified_at=c.last_verified_at,
                consecutive_failures=0,
                not_seen=False,
            )
            log_status(session, c, st, f"first seen on the official page ({url}); {why}", now)
            _check(session, c, o.last_confirmed_at, "seen", report, detail=url)
            report.new_campaigns.append(key)
            existing[key] = c
            continue
        latest = _latest(c)
        changed = terms.material_hash(t) != latest.material_hash
        if changed:
            changes = terms.diff(latest.terms, t)
            add_version(session, c, t, now, url=url, excerpt=excerpt, changes=changes)
            report.new_versions.append(
                f"{key} v{c.current_version}: " + ", ".join(ch["field"] for ch in changes)
            )
        if c.last_verified_at is None or o.last_confirmed_at > c.last_verified_at:
            _check(session, c, o.last_confirmed_at, "changed" if changed else "seen", report, detail=url)
            c.last_verified_at = o.last_confirmed_at
            c.consecutive_failures = 0
        if str(o.id) not in (c.prod_offer_ids or []):
            c.prod_offer_ids = [*(c.prod_offer_ids or []), str(o.id)]

    # checks for every official campaign of the card from the runs since its last check
    for key, c in existing.items():
        if c.source_kind != "official" or c.status in status.FINAL:
            continue
        seen_now = key in current
        not_seen = c.status == "pending_verification" and not seen_now
        for rs in _runs_since(session, card.source_ids, c.last_checked_at):
            if rs.terminal_status in SUCCESS:
                if seen_now and c.last_verified_at is not None and c.last_verified_at >= rs.at - _SEEN_SLACK:
                    continue  # recorded above as seen/changed
                if not seen_now:
                    not_seen = True
                    _check(
                        session,
                        c,
                        rs.at,
                        "not_seen",
                        report,
                        run_id=rs.run_id,
                        source_id=rs.source_id,
                        detail="the official page was captured but no longer shows this offer",
                    )
            else:
                c.consecutive_failures += 1
                _check(
                    session,
                    c,
                    rs.at,
                    "failed",
                    report,
                    run_id=rs.run_id,
                    source_id=rs.source_id,
                    detail=f"{rs.terminal_status}{f' ({rs.failure})' if rs.failure else ''}",
                )
        c.last_checked_at = now
        st, why = status.compute(
            c.status,
            end=_latest(c).terms.get("end"),
            now=now,
            last_verified_at=c.last_verified_at,
            consecutive_failures=c.consecutive_failures,
            not_seen=not_seen and not seen_now,
        )
        if st != c.status:
            report.status_changes.append(f"{key}: {c.status} → {st} ({why})")
            log_status(session, c, st, why, now)


def refresh_statuses(session: Session, now: datetime, report: SyncReport) -> None:
    """Date-driven transitions (ending soon, expired) for every campaign, including manual ones."""
    for c in session.scalars(select(P.Campaign).where(P.Campaign.status.notin_(list(status.FINAL)))):
        st, why = status.compute(
            c.status,
            end=_latest(c).terms.get("end"),
            now=now,
            last_verified_at=c.last_verified_at,
            consecutive_failures=c.consecutive_failures,
            not_seen=c.status == "pending_verification",
        )
        if c.source_kind != "official" and st == "stale":
            continue  # manual entries are not re-checked automatically; their age is shown instead
        if st != c.status:
            report.status_changes.append(f"{c.campaign_key}: {c.status} → {st} ({why})")
            log_status(session, c, st, why, now)


def sync(session: Session, now: datetime) -> SyncReport:
    report = SyncReport()
    cards = sync_cards(session, report)
    sync_rules(session, report)
    for card in cards.values():
        sync_campaigns(session, card, now, report)
    session.flush()
    refresh_statuses(session, now, report)
    session.flush()
    return report
