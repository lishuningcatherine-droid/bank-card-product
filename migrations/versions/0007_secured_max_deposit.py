"""credit_card_details.secured_max_deposit_cents (secured cards state both ends of the deposit range)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_card_details",
        sa.Column("secured_max_deposit_cents", sa.BigInteger(), nullable=True),
        schema="prod",
    )


def downgrade() -> None:
    op.drop_column("credit_card_details", "secured_max_deposit_cents", schema="prod")
