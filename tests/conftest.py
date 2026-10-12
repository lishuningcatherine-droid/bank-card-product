from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures"
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bankrec:bankrec@localhost:5432/bankrec_test"
)


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    """Real PostgreSQL. Uses TEST_DATABASE_URL (local cluster or compose service)."""
    from sqlalchemy import create_engine, text

    try:
        eng = create_engine(TEST_DB)
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"PostgreSQL not available at {TEST_DB}: {e}")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.attributes["url"] = TEST_DB
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DB


@pytest.fixture
def engine(db_url: str):  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine, text

    eng = create_engine(db_url)
    with eng.begin() as c:
        tables = (
            c.execute(
                text(
                    "select schemaname||'.'||tablename from pg_tables where schemaname in ('staging','prod')"
                )
            )
            .scalars()
            .all()
        )
        c.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from bankrec.settings import Settings

    return Settings(
        BANKREC_ENV="test",
        BANKREC_DATA_DIR=tmp_path / "data",
        BANKREC_REPORTS_DIR=tmp_path / "reports",
        BANKREC_MIN_HOST_INTERVAL_S=0,
    )
