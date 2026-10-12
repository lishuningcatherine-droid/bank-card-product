from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from bankrec.db import prod, staging  # noqa: F401  (register models)
from bankrec.db.base import ProdBase, StagingBase
from bankrec.settings import get_settings

target_metadata = [StagingBase.metadata, ProdBase.metadata]


def include_name(name, type_, parent_names):  # type: ignore[no-untyped-def]
    if type_ == "schema":
        return name in {"staging", "prod"}
    return True


def run_migrations_online() -> None:
    url = context.config.attributes.get("url") or get_settings().database_url
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="public",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
