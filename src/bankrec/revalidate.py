"""Dispatch the revalidation outbox to the signed Next.js endpoint (DESIGN §21.4)."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bankrec.alerts import sign
from bankrec.db import staging as S
from bankrec.settings import Settings

log = logging.getLogger("bankrec.revalidate")
MAX_TAGS = 200


def dispatch(
    session: Session,
    settings: Settings,
    now: datetime,
    client: httpx.Client | None = None,
    max_attempts: int = 10,
) -> dict[str, int]:
    stats = {"sent": 0, "failed": 0, "pending": 0}
    rows = list(
        session.scalars(
            select(S.RevalidationOutbox)
            .where(
                S.RevalidationOutbox.sent_at.is_(None),
                S.RevalidationOutbox.attempts < max_attempts,
                or_(S.RevalidationOutbox.not_before.is_(None), S.RevalidationOutbox.not_before <= now),
            )
            .order_by(S.RevalidationOutbox.id)
        )
    )
    if not rows:
        return stats
    if not settings.revalidate_url or not settings.revalidate_secret:
        stats["pending"] = len(rows)
        log.info("revalidation endpoint not configured; %d outbox rows pending", len(rows))
        return stats
    c = client or httpx.Client(timeout=10)
    for row in rows:
        body = json.dumps({"tags": row.tags[:MAX_TAGS]}).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Bankrec-Signature": sign(settings.revalidate_secret, body),
        }
        row.attempts += 1
        try:
            r = c.post(settings.revalidate_url, content=body, headers=headers)
            if r.status_code < 300:
                row.sent_at = now
                stats["sent"] += 1
                continue
            row.last_error = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            row.last_error = type(e).__name__
        stats["failed"] += 1
    return stats
