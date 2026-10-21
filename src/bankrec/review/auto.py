"""Auto-approval of pure, page-evidenced additions (owner rule 2026-10-20; DESIGN §26.1).

An open ``product / major_change`` item is approved without the owner only when *every* change adds something and
nothing existing is changed or removed:

* a field that was empty now has a value;
* a new offer appears on a product that had no offer of that type (``offer_appeared``);
* earn rates or benefits gain entries while every published entry stays exactly as it was.

and the item carries no conflict, no failed validation rule and no missing key field (the capture already passed the
quality gate, or it would not have been extracted). Everything else — a changed or removed value, a replaced offer,
a duplicate, a failed check — waits for the owner. Each approval is logged with reviewer ``claude-auto`` and listed in
docs/AUTO_APPROVED.md.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import staging as S
from bankrec.publish.changes import _canon
from bankrec.registry.loader import Registry
from bankrec.review.service import approve

REVIEWER = "claude-auto"


def _is_addition(ch: dict[str, Any]) -> bool:
    rule, old, new = ch.get("rule"), ch.get("old"), ch.get("new")
    if str(ch.get("field", "")).startswith("offer:"):
        return rule == "offer_appeared" and old is None  # offer_changed replaces an offer
    if ch.get("field") in ("reward_rates", "benefits"):
        before, after = _canon(old), _canon(new)
        return len(after) > len(before) and all(after.count(x) >= before.count(x) for x in set(before))
    return old is None and new is not None


def why_not(it: S.ManualReviewItem) -> str | None:
    """None when the item may be auto-approved, else the reason it waits for the owner."""
    if (it.item_kind, it.reason_code) != ("product", "major_change"):
        return f"{it.item_kind}/{it.reason_code} items need the owner"
    ctx = it.context or {}
    if ctx.get("conflicts"):
        return "sources conflict"
    if ctx.get("failed_rules"):
        return "a validation rule failed"
    if ctx.get("missing_key"):
        return "a key field is missing"
    changes = ctx.get("changes") or []
    if not changes:
        return "no change recorded"
    bad = [c.get("field") for c in changes if not _is_addition(c)]
    return f"changes or removes existing values: {', '.join(map(str, bad))}" if bad else None


def summary(it: S.ManualReviewItem) -> str:
    parts = []
    for c in (it.context or {}).get("changes") or []:
        if c.get("rule") == "offer_appeared":
            parts.append(f"new {str(c.get('field')).removeprefix('offer:')} offer")
        elif c.get("field") in ("reward_rates", "benefits"):
            added = len(_canon(c.get("new"))) - len(_canon(c.get("old")))
            parts.append(f"{added} {str(c.get('field')).replace('_', ' ')} added")
        else:
            parts.append(f"{c.get('field')} = {c.get('new')}")
    return "; ".join(parts)


def run(
    session: Session, registry: Registry, now: datetime, *, dry_run: bool = False
) -> list[dict[str, Any]]:
    out = []
    items = session.scalars(
        select(S.ManualReviewItem).where(S.ManualReviewItem.state == "open").order_by(S.ManualReviewItem.id)
    ).all()
    for it in items:
        if why_not(it) is not None:
            continue
        ctx = it.context or {}
        row = {"id": it.id, "product": ctx.get("name"), "content": summary(it), "source": ctx.get("url")}
        if not dry_run:
            approve(
                session,
                registry,
                it.id,
                reviewer=REVIEWER,
                note=f"auto-approved: pure page-evidenced addition ({row['content']}) from {row['source']}",
                now=now,
            )
        out.append(row)
    return out


def write_log(session: Session, path: Path, now: datetime) -> int:
    """docs/AUTO_APPROVED.md: every auto-approval so far, newest first, for the owner's spot checks."""
    rows = session.execute(
        select(S.ReviewDecision, S.ManualReviewItem)
        .join(S.ManualReviewItem, S.ManualReviewItem.id == S.ReviewDecision.queue_id)
        .where(S.ReviewDecision.reviewer == REVIEWER, S.ReviewDecision.action == "approve")
        .order_by(S.ReviewDecision.decided_at.desc(), S.ReviewDecision.queue_id.desc())
    ).all()
    lines = [
        "# Auto-approved review items",
        "",
        f"Generated {now:%Y-%m-%d %H:%M} UTC by `bankrec review auto-approve`. Owner rule (2026-10-20): Claude may "
        "approve only pure additions backed by page text that pass every check (quality gate, completeness, "
        "consistency); any change or removal of an existing value waits for the owner. Spot-check any row with "
        "`uv run bankrec review show <id>`.",
        "",
        "| Approved (UTC) | Item | Product | Added | Source |",
        "|---|---|---|---|---|",
    ]
    for d, it in rows:
        ctx = it.context or {}
        lines.append(
            f"| {d.decided_at:%Y-%m-%d %H:%M} | {it.id} | {ctx.get('name', '')} | {summary(it)} | <{ctx.get('url', '')}> |"
        )
    if not rows:
        lines.append("| — | — | — | nothing auto-approved yet | — |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)
