"""offers.amount_qualifier may be 'tiered' (amount_max = sum of the tiers; tiers stored separately)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "(amount_qualifier = 'exact' AND amount_min IS NOT NULL AND amount_min = amount_max) OR "
    "(amount_qualifier = 'up_to' AND amount_min IS NULL AND amount_max IS NOT NULL) OR "
    "(amount_qualifier = 'starting_at' AND amount_min IS NOT NULL AND amount_max IS NULL)"
)
_NEW = (
    _OLD + " OR (amount_qualifier = 'tiered' AND amount_max IS NOT NULL AND jsonb_array_length(tiers) >= 2)"
)


def upgrade() -> None:
    op.drop_constraint("ck_offers_amount_qualifier_shape", "offers", schema="prod")
    op.create_check_constraint("ck_offers_amount_qualifier_shape", "offers", _NEW, schema="prod")


def downgrade() -> None:
    op.drop_constraint("ck_offers_amount_qualifier_shape", "offers", schema="prod")
    # the old shape has no tiers: keep the maximum as an "up to" amount
    op.execute(
        "UPDATE prod.offers SET amount_qualifier = 'up_to', amount_min = NULL WHERE amount_qualifier = 'tiered'"
    )
    op.create_check_constraint("ck_offers_amount_qualifier_shape", "offers", _OLD, schema="prod")
