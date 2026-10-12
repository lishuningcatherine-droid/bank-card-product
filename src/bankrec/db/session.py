from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from bankrec.settings import get_settings


@lru_cache(maxsize=4)
def engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, future=True)


def get_engine(readonly: bool = False) -> Engine:
    s = get_settings()
    return engine_for((s.api_database_url or s.database_url) if readonly else s.database_url)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    sess = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
