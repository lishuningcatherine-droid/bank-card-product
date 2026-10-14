"""credit_card_details: restricted-redemption reward currency (name, value per unit, where it can be redeemed)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_card_details", sa.Column("reward_currency_name", sa.Text(), nullable=True), schema="prod"
    )
    op.add_column(
        "credit_card_details", sa.Column("redemption_value_cents", sa.Integer(), nullable=True), schema="prod"
    )
    op.add_column(
        "credit_card_details", sa.Column("redemption_restriction", sa.Text(), nullable=True), schema="prod"
    )


def downgrade() -> None:
    for c in ("redemption_restriction", "redemption_value_cents", "reward_currency_name"):
        op.drop_column("credit_card_details", c, schema="prod")
