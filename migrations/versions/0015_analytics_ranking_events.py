"""analytics.ranking_events: consented, anonymous ranking events (DESIGN §26.7)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.create_table(
        "ranking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event", sa.String(length=24), nullable=False),
        sa.Column("product_type", sa.String(length=12), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("shown", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("ranker", sa.String(length=64), nullable=False),
        sa.Column("occurred_hour", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event IN ('results_shown', 'result_opened', 'official_link_clicked', 'compare_added')",
            name=op.f("ck_ranking_events_event"),
        ),
        sa.CheckConstraint(
            "product_type IN ('credit_card', 'checking', 'savings')",
            name=op.f("ck_ranking_events_product_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ranking_events")),
        schema="analytics",
    )
    for col in ("anon_id", "list_id", "occurred_hour"):
        op.create_index(
            op.f(f"ix_analytics_ranking_events_{col}"),
            "ranking_events",
            [col],
            unique=False,
            schema="analytics",
        )
    # the public API's role may record and delete events, and read nothing else in this schema's sense of use
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bankrec_api') THEN
            GRANT USAGE ON SCHEMA analytics TO bankrec_api;
            GRANT INSERT, DELETE ON analytics.ranking_events TO bankrec_api;
            GRANT SELECT (anon_id) ON analytics.ranking_events TO bankrec_api;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("ranking_events", schema="analytics")
    op.execute("DROP SCHEMA IF EXISTS analytics")
