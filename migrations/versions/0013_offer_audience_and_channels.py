"""offers.audience adds referral and preapproved; offers.seen_on (every official page that showed the offer)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_offers_audience", "offers", schema="prod")
    op.alter_column("offers", "audience", type_=sa.String(length=12), schema="prod")
    op.create_check_constraint(
        "ck_offers_audience",
        "offers",
        "audience IN ('public','targeted','referral','preapproved')",
        schema="prod",
    )
    op.add_column(
        "offers",
        sa.Column("seen_on", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        schema="prod",
    )
    # existing rows: the page they were last read from (source and channel are filled on the next confirmation)
    op.execute(
        "UPDATE prod.offers SET seen_on = jsonb_build_array(jsonb_build_object("
        "'url', offer_url, 'source_id', NULL, 'channel', NULL, "
        "'first_seen_at', to_jsonb(retrieved_at), 'last_confirmed_at', to_jsonb(last_confirmed_at)))"
    )


def downgrade() -> None:
    op.drop_column("offers", "seen_on", schema="prod")
    op.drop_constraint("ck_offers_audience", "offers", schema="prod")
    # the old schema knows only public and targeted: other non-public offers stay non-public
    op.execute("UPDATE prod.offers SET audience = 'targeted' WHERE audience IN ('referral', 'preapproved')")
    op.alter_column("offers", "audience", type_=sa.String(length=10), schema="prod")
    op.create_check_constraint(
        "ck_offers_audience", "offers", "audience IN ('public','targeted')", schema="prod"
    )
