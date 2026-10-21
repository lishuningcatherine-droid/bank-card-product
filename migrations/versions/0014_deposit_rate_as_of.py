"""checking/savings rate_as_of_date and rate_as_of_text (the date the bank's page states its rates are effective as of)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("checking_account_details", "savings_account_details")


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("rate_as_of_date", sa.Date(), nullable=True), schema="prod")
        op.add_column(t, sa.Column("rate_as_of_text", sa.Text(), nullable=True), schema="prod")


def downgrade() -> None:
    for t in _TABLES:
        op.drop_column(t, "rate_as_of_text", schema="prod")
        op.drop_column(t, "rate_as_of_date", schema="prod")
