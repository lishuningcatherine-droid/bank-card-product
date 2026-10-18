"""credit_card_details.intro_bt_window_days; product_benefits.condition

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_card_details", sa.Column("intro_bt_window_days", sa.Integer(), nullable=True), schema="prod"
    )
    op.add_column("product_benefits", sa.Column("condition", sa.Text(), nullable=True), schema="prod")


def downgrade() -> None:
    op.drop_column("product_benefits", "condition", schema="prod")
    op.drop_column("credit_card_details", "intro_bt_window_days", schema="prod")
