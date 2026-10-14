"""credit_card_details.intro_apr_period_unit (months | billing_cycles | statement_closings)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_card_details",
        sa.Column("intro_apr_period_unit", sa.String(length=20), nullable=True),
        schema="prod",
    )
    op.create_check_constraint(
        "ck_credit_card_details_intro_apr_period_unit",
        "credit_card_details",
        "intro_apr_period_unit IS NULL OR intro_apr_period_unit IN ('months', 'billing_cycles', 'statement_closings')",
        schema="prod",
    )


def downgrade() -> None:
    op.drop_constraint("ck_credit_card_details_intro_apr_period_unit", "credit_card_details", schema="prod")
    op.drop_column("credit_card_details", "intro_apr_period_unit", schema="prod")
