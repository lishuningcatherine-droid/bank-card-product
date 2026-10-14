"""product_reward_rates.conditions: structured qualifiers ({kind, text, detail}) with the page words

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_reward_rates",
        sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        schema="prod",
    )
    # Existing portal-only rates keep their qualifier as a structured condition (the rate text is the evidence).
    op.execute(
        "UPDATE prod.product_reward_rates SET conditions = jsonb_build_array(jsonb_build_object("
        "'kind', 'portal_only', 'text', conditions_text, 'detail', NULL)) WHERE portal_only"
    )


def downgrade() -> None:
    op.drop_column("product_reward_rates", "conditions", schema="prod")
