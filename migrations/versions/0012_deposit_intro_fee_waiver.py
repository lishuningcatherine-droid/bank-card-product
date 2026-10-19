"""checking/savings intro_fee_waiver (new-account fee waiver, as stated)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("checking_account_details", "savings_account_details"):
        op.add_column(table, sa.Column("intro_fee_waiver", postgresql.JSONB(), nullable=True), schema="prod")


def downgrade() -> None:
    for table in ("checking_account_details", "savings_account_details"):
        op.drop_column(table, "intro_fee_waiver", schema="prod")
