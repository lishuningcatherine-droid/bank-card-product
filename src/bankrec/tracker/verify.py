"""Excerpt checks: each rule or point value marked as captured from a page must still be in that page's latest
capture (whitespace-normalised). A missing excerpt means the page changed; the item needs review."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import staging as S
from bankrec.tracker import config


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _latest_text(session: Session, source_id: str) -> str | None:
    path = session.scalar(
        select(S.PageSnapshot.text_path)
        .where(S.PageSnapshot.source_id == source_id, S.PageSnapshot.outcome == "ok")
        .order_by(S.PageSnapshot.retrieved_at.desc())
        .limit(1)
    )
    if not path or not Path(path).exists():
        return None
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def verify_excerpts(session: Session) -> list[str]:
    out: list[str] = []
    items = [
        (f"rule {r['rule_key']}", r.get("source_id"), r["excerpt"], r.get("verification"))
        for r in config.rules()
    ]
    items += [
        (
            f"point value {k}",
            v.get("source_id") or _source_for(v.get("source_url")),
            v["excerpt"],
            "page_captured",
        )
        for k, v in config.programs().items()
        if v.get("excerpt")
    ]
    for what, sid, excerpt, verification in items:
        if verification != "page_captured":
            continue
        if not sid:
            out.append(f"{what}: no source_id")
            continue
        text = _latest_text(session, sid)
        if text is None:
            out.append(f"{what}: no capture of {sid}")
            continue
        parts = [p for p in re.split(r"\s*\.\.\.\s*", excerpt) if p.strip()]
        missing = [p for p in parts if _norm(p) not in _norm(text)]
        if missing:
            out.append(f"{what}: not in the latest capture of {sid}: “{missing[0][:120]}”")
    return out


def _source_for(url: str | None) -> str | None:
    if not url:
        return None
    for c in config.cards():
        for sid in c.get("source_ids", []):
            _bank, slug = sid.split(":", 1)
            if slug and slug in url:
                return sid
    return None
