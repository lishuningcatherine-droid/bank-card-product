"""Tiered scheduling helpers: crontab generation and per-tier advisory locks (DESIGN §21.1)."""

from __future__ import annotations

import zlib

from sqlalchemy import text
from sqlalchemy.engine import Connection

from bankrec.freshness import config


def crontab(binary: str = "bankrec") -> str:
    lines = ["# Generated from config/freshness.yaml by `bankrec schedule crontab`. Times are UTC."]
    for tier, spec in config()["tiers"].items():
        lines.append(f"{spec['schedule']} {binary} ingest --tier {tier} --trigger cron")
    lines.append("*/5 * * * * " + binary + " revalidate dispatch")
    lines.append("17 3 * * * " + binary + " events purge")  # consented ranking events past their retention
    return "\n".join(lines) + "\n"


def lock_key(tier: str) -> int:
    return zlib.crc32(f"bankrec-ingest-{tier}".encode()) & 0x7FFFFFFF


def try_lock(conn: Connection, tier: str) -> bool:
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key(tier)}).scalar())


def unlock(conn: Connection, tier: str) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key(tier)})
