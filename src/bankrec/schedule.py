"""Tiered scheduling helpers: crontab generation and per-tier advisory locks (DESIGN §21.1)."""

from __future__ import annotations

import logging
import os
import zlib

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from bankrec.freshness import config

log = logging.getLogger("bankrec.schedule")


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


def is_pooled(engine: Engine) -> bool:
    """A pooled endpoint (PgBouncer in transaction mode, e.g. Neon's ``-pooler`` host) can hand each transaction to a
    different server session, so a session-level advisory lock would not hold. ``BANKREC_DB_POOLED=1`` declares
    any other pooled endpoint."""
    host = engine.url.host or ""
    return "-pooler." in host or os.environ.get("BANKREC_DB_POOLED") == "1"


class LockLost(RuntimeError):
    """The connection holding the tier lock is gone, so another run may have started: stop before committing."""


class TierLock:
    """The per-tier advisory lock for a scheduled run (DESIGN §21.1).

    Direct connection: a session-level lock on its own **autocommit** connection, so the lock connection is never
    "idle in transaction" and a server-side ``idle_in_transaction_session_timeout`` (Neon sets one) cannot end it
    while the run works on other connections.

    Pooled connection (PgBouncer in transaction mode): a session lock would not hold, so it is a transaction-level
    lock in a transaction kept open for the run; that transaction disables the idle timeout for itself only
    (``SET LOCAL``). The scheduled workflow refuses pooled addresses anyway.

    Call :meth:`ensure` before each commit of the run's work: if the lock connection was lost it raises
    :class:`LockLost`, so the uncommitted work is rolled back instead of being written without the lock."""

    def __init__(self, engine: Engine, tier: str) -> None:
        self.engine, self.tier, self.key = engine, tier, lock_key(tier)
        self.pooled = is_pooled(engine)
        self.conn: Connection | None = None

    def acquire(self) -> bool:
        if self.pooled:
            conn = self.engine.connect()
            conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
            got = conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": self.key}).scalar()
        else:
            conn = self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
            got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar()
        if not got:
            conn.close()
            return False
        self.conn = conn
        return True

    def alive(self) -> bool:
        """Whether this run still holds the lock (its connection is open and the server still lists the lock)."""
        if self.conn is None:
            return False
        try:
            return bool(
                self.conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted"
                        " AND pid = pg_backend_pid() AND classid = 0 AND objid = :k AND objsubid = 1)"
                    ),
                    {"k": self.key},
                ).scalar()
            )
        except SQLAlchemyError:
            self.conn.invalidate()  # the server ended the session; never reuse this connection
            return False

    def ensure(self) -> None:
        if not self.alive():
            raise LockLost(
                f"lost the database lock for tier {self.tier} (its connection was closed by the server); "
                "the work not yet committed was rolled back"
            )

    def release(self) -> None:
        """Release the lock. Never raises: if the connection is already gone the server released the lock when that
        session ended, so a failed unlock is only logged."""
        conn, self.conn = self.conn, None
        if conn is None:
            return
        try:
            if self.pooled:
                conn.rollback()  # ends the lock's transaction, which releases a transaction-level lock
            else:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
        except SQLAlchemyError as e:
            log.warning(
                "tier lock %s: unlock failed (%s); the server released it when the connection ended",
                self.tier,
                type(getattr(e, "orig", None) or e).__name__,
            )
            conn.invalidate()
        finally:
            conn.close()
