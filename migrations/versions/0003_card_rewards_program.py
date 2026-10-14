"""credit_card_details.rewards_program ("none" = evidence-backed no rewards program)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_card_details",
        sa.Column("rewards_program", sa.String(length=10), nullable=True),
        schema="prod",
    )
    op.create_check_constraint(
        "ck_credit_card_details_rewards_program",
        "credit_card_details",
        "rewards_program IS NULL OR rewards_program = 'none'",
        schema="prod",
    )


def downgrade() -> None:
    op.drop_constraint("ck_credit_card_details_rewards_program", "credit_card_details", schema="prod")
    op.drop_column("credit_card_details", "rewards_program", schema="prod")
