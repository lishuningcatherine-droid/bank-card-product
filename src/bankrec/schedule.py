"""Tiered scheduling helpers: crontab generation and per-tier advisory locks (DESIGN §21.1)."""

from __future__ import annotations

import os
import zlib

from sqlalchemy import text
from sqlalchemy.engine import Connection

from bankrec.freshness import config


def crontab(binary: str = "bankrec") -> str:
    lines = ["# Generated from config/freshness.yaml by `bankrec schedule crontab`. Times are UTC."]
    for tier, spec in config()["tiers"].items():
        lines.append(f"{spec['schedule']} {binary} ingest --tier {tier} --trigger cron")
    from bankrec.tracker import config as tracker

    # the offer tracker reads what the ingestion published: campaigns, versions, checks and statuses (DESIGN §27.7)
    sync_at = (tracker.settings().get("update") or {}).get("sync_schedule")
    if sync_at:
        lines.append(f"{sync_at} {binary} offers sync")
    lines.append("*/5 * * * * " + binary + " revalidate dispatch")
    lines.append("17 3 * * * " + binary + " events purge")  # consented ranking events past their retention
    return "\n".join(lines) + "\n"


def lock_key(tier: str) -> int:
    return zlib.crc32(f"bankrec-ingest-{tier}".encode()) & 0x7FFFFFFF


def is_pooled(conn: Connection) -> bool:
    """A pooled endpoint (PgBouncer in transaction mode, e.g. Neon's ``-pooler`` host) can hand each transaction to a
    different server session, so a session-level advisory lock would not hold. ``BANKREC_DB_POOLED=1`` declares
    any other pooled endpoint."""
    host = conn.engine.url.host or ""
    return "-pooler." in host or os.environ.get("BANKREC_DB_POOLED") == "1"


def try_lock(conn: Connection, tier: str) -> bool:
    """Take the tier's lock on ``conn``, a connection kept open for the whole run.

    Direct connection: a session-level advisory lock. Pooled connection: a transaction-level lock in a transaction
    kept open until :func:`unlock` (the open transaction pins one server session, so the lock holds)."""
    if is_pooled(conn):
        return bool(
            conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key(tier)}).scalar()
        )
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key(tier)}).scalar())


def unlock(conn: Connection, tier: str) -> None:
    if is_pooled(conn):
        conn.rollback()  # ends the lock's transaction, which releases a transaction-level lock
        return
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key(tier)})
