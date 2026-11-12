"""The scheduled run's tier lock under a server-side idle_in_transaction_session_timeout (Neon sets one; a local
PostgreSQL does not, which is how the first test-branch run failed on unlock). Every test here sets the timeout to
2 seconds on its own connections and runs work that takes longer (DESIGN §21.1)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

IDLE_MS = 2000
SLOW_S = 2.6  # longer than the timeout


def with_idle_timeout(url: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options=-c%20idle_in_transaction_session_timeout%3D{IDLE_MS}"


@pytest.fixture
def idle_engine(engine: Engine, db_url: str) -> Iterator[Engine]:
    """Connections that the server ends after 2 s idle inside a transaction (``engine`` empties the tables)."""
    eng = create_engine(with_idle_timeout(db_url))
    with eng.connect() as c:
        assert c.execute(text("SHOW idle_in_transaction_session_timeout")).scalar() == "2s"
    yield eng
    eng.dispose()


def holder_pid(engine: Engine, tier: str) -> int | None:
    from bankrec.schedule import lock_key

    with engine.connect() as c:
        return c.execute(
            text("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted AND objid = :k"),
            {"k": lock_key(tier)},
        ).scalar()


def session_state(engine: Engine, pid: int | None) -> str | None:
    with engine.connect() as c:
        return c.execute(text("SELECT state FROM pg_stat_activity WHERE pid = :p"), {"p": pid}).scalar()


def test_old_pattern_reproduces_the_neon_failure(idle_engine: Engine) -> None:
    """What the first scheduled run did: lock on an ordinary connection, which then sat idle in its transaction
    for the whole scrape; the server ended it and the unlock failed."""
    from bankrec.schedule import lock_key

    conn = idle_engine.connect()
    try:
        assert conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key("old")}).scalar()
        time.sleep(SLOW_S)
        with pytest.raises(DBAPIError, match="IdleInTransactionSessionTimeout"):
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key("old")})
    finally:
        conn.invalidate()
        conn.close()


def test_lock_survives_a_slow_job_and_still_excludes_other_runs(idle_engine: Engine, caplog) -> None:  # type: ignore[no-untyped-def]
    from bankrec.schedule import TierLock

    lock, other = TierLock(idle_engine, "offer"), TierLock(idle_engine, "offer")
    assert lock.acquire()
    try:
        for i in range(
            3
        ):  # the job: slow steps, its database work in short transactions on other connections
            time.sleep(SLOW_S / 2)
            with idle_engine.begin() as c:
                c.execute(text("SELECT :i"), {"i": i})
        assert (
            session_state(idle_engine, holder_pid(idle_engine, "offer")) == "idle"
        )  # not "idle in transaction"
        assert lock.alive()
        assert not other.acquire()
        lock.ensure()
    finally:
        with caplog.at_level(logging.WARNING, logger="bankrec.schedule"):
            lock.release()
    assert not caplog.records  # a clean unlock
    assert holder_pid(idle_engine, "offer") is None
    assert other.acquire()
    other.release()


def test_lost_lock_connection_fails_clearly_and_unlock_is_not_fatal(idle_engine: Engine, caplog) -> None:  # type: ignore[no-untyped-def]
    from bankrec.schedule import LockLost, TierLock

    lock = TierLock(idle_engine, "apy")
    assert lock.acquire()
    pid = holder_pid(idle_engine, "apy")
    with idle_engine.connect() as c:  # the server drops the lock's connection (as Neon's timeout would)
        assert c.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar()
    assert not lock.alive()
    with pytest.raises(LockLost, match="rolled back"):
        lock.ensure()
    with caplog.at_level(logging.WARNING, logger="bankrec.schedule"):
        lock.release()  # does not raise: the server released the lock when the session ended
    assert "unlock failed" in caplog.text and "released it" in caplog.text
    assert holder_pid(idle_engine, "apy") is None
    again = TierLock(idle_engine, "apy")
    assert again.acquire()
    again.release()


def test_pooled_endpoint_holds_a_transaction_lock_without_the_idle_timeout(
    idle_engine: Engine, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Behind PgBouncer in transaction mode a session lock would not hold, so the lock is a transaction-level lock in
    a transaction kept open for the run; that transaction turns the idle timeout off for itself only."""
    from bankrec.schedule import TierLock, is_pooled

    monkeypatch.setenv("BANKREC_DB_POOLED", "1")
    assert is_pooled(idle_engine)
    lock, other = TierLock(idle_engine, "terms"), TierLock(idle_engine, "terms")
    assert lock.acquire()
    assert session_state(idle_engine, holder_pid(idle_engine, "terms")) == "idle in transaction"
    time.sleep(SLOW_S)  # longer than the timeout, which this transaction turned off for itself
    assert lock.alive() and not other.acquire()
    lock.release()
    assert other.acquire()
    other.release()
    monkeypatch.delenv("BANKREC_DB_POOLED")
    assert not is_pooled(idle_engine)


def run_ingest(db_url: str, tmp_path: Path, monkeypatch) -> object:  # type: ignore[no-untyped-def]
    from bankrec.cli.main import app
    from bankrec.db.session import engine_for
    from bankrec.settings import get_settings

    monkeypatch.setenv("DATABASE_URL", with_idle_timeout(db_url))
    monkeypatch.setenv("BANKREC_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("BANKREC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BANKREC_MIN_HOST_INTERVAL_S", "0")
    get_settings.cache_clear()
    engine_for.cache_clear()
    try:
        return CliRunner().invoke(
            app,
            ["ingest", "--include-test", "--bank", "example_bank", "--source", "example_bank:everyday-cash",
             "--source", "example_bank:voyager-rewards", "--no-render"],
        )  # fmt: skip
    finally:
        engine_for.cache_clear()
        get_settings.cache_clear()


def scrape_runs(engine: Engine) -> int:
    with engine.connect() as c:
        return int(c.execute(text("SELECT count(*) FROM staging.scrape_runs")).scalar_one())


def test_slow_ingest_completes_under_the_idle_timeout(
    idle_engine: Engine, db_url, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A run whose page loads each take longer than the timeout: the lock connection never sits in a transaction,
    and the pipeline loads every page before its (short) database transaction."""
    from bankrec.ingest.fetch import FixtureFetcher

    real = FixtureFetcher.fetch

    def slow(self, src, bank):  # type: ignore[no-untyped-def]
        time.sleep(SLOW_S)
        return real(self, src, bank)

    monkeypatch.setattr(FixtureFetcher, "fetch", slow)
    res = run_ingest(db_url, tmp_path, monkeypatch)
    assert res.exit_code == 0, res.output  # type: ignore[attr-defined]
    assert scrape_runs(idle_engine) == 1
    assert holder_pid(idle_engine, "all") is None


def test_ingest_that_loses_its_lock_saves_nothing(idle_engine: Engine, db_url, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from bankrec.ingest.pipeline import Pipeline

    real = Pipeline.run

    def run_then_drop_lock(self, *a, **kw):  # type: ignore[no-untyped-def]
        out = real(self, *a, **kw)
        with idle_engine.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(:p)"), {"p": holder_pid(idle_engine, "all")})
        return out

    monkeypatch.setattr(Pipeline, "run", run_then_drop_lock)
    res = run_ingest(db_url, tmp_path, monkeypatch)
    assert res.exit_code == 4, res.output  # type: ignore[attr-defined]
    assert "lost the database lock for tier all" in res.output  # type: ignore[attr-defined]
    assert scrape_runs(idle_engine) == 0  # the run's work was rolled back, not half-written
    assert holder_pid(idle_engine, "all") is None
