"""Parser-regression alerts: log + report + optional signed webhook, deduplicated per incident (DESIGN §21.6)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.publish.publisher import enqueue_revalidation, product_tags
from bankrec.settings import Settings

log = logging.getLogger("bankrec.alerts")


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    t = ts if ts is not None else int(time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def _send(settings: Settings, payload: dict[str, Any], client: httpx.Client | None) -> bool:
    if not settings.alert_webhook_url or not settings.alert_webhook_secret:
        return False
    body = json.dumps(payload, sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Bankrec-Signature": sign(settings.alert_webhook_secret, body),
    }
    try:
        c = client or httpx.Client(timeout=10)
        r = c.post(settings.alert_webhook_url, content=body, headers=headers)
        return r.status_code < 300
    except httpx.HTTPError:
        log.warning("alert webhook delivery failed")
        return False


def open_regression(
    session: Session,
    settings: Settings,
    *,
    source_id: str,
    bank_id: str,
    url: str,
    kind: str,
    parser_version: str | None,
    run_id: str,
    now: datetime,
    last_good: datetime | None,
    client: httpx.Client | None = None,
) -> S.Alert | None:
    """Open (once per incident) and downgrade affected records. Returns the alert if newly opened."""
    existing = session.scalar(
        select(S.Alert).where(
            S.Alert.source_id == source_id, S.Alert.state == "open", S.Alert.kind == "parser_regression"
        )
    )
    downgrade(session, source_id, reason="parser_failure", now=now)
    if existing is not None:
        return None
    payload = {
        "event": "parser_regression",
        "bank_id": bank_id,
        "source_id": source_id,
        "url": url,
        "failure_kind": kind,
        "parser_version": parser_version,
        "first_seen": now.isoformat(),
        "last_good": last_good.isoformat() if last_good else None,
        "run_id": run_id,
    }
    log.error("parser_regression", extra={"event": "parser_regression", **payload})
    alert = S.Alert(
        kind="parser_regression", source_id=source_id, state="open", opened_at=now, payload=payload
    )
    alert.webhook_open_sent = _send(settings, payload, client)
    session.add(alert)
    return alert


def resolve(
    session: Session, settings: Settings, source_id: str, now: datetime, client: httpx.Client | None = None
) -> None:
    for a in session.scalars(select(S.Alert).where(S.Alert.source_id == source_id, S.Alert.state == "open")):
        a.state, a.resolved_at = "resolved", now
        payload = {**a.payload, "event": "parser_regression_resolved", "resolved_at": now.isoformat()}
        log.info(
            "parser_regression_resolved",
            extra={"event": "parser_regression_resolved", "source_id": source_id},
        )
        a.webhook_resolved_sent = _send(settings, payload, client)


def downgrade(session: Session, source_id: str, *, reason: str, now: datetime) -> list[P.Product]:
    """Mark products and offers backed by ``source_id`` as recheck-pending (→ Partially verified)."""
    pids = set(
        session.scalars(select(P.FieldProvenance.product_id).where(P.FieldProvenance.source_id == source_id))
    )
    products = [p for p in (session.get(P.Product, pid) for pid in pids) if p is not None]
    for p in products:
        if not p.recheck_pending:
            p.recheck_pending, p.recheck_reason = True, reason
            enqueue_revalidation(session, product_tags(p), now)
        for o in p.offers:
            if o.status == "current":
                o.status, o.recheck_reason = "recheck_pending", reason
    return products
