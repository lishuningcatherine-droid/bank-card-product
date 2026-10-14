"""products.offer_status: captured | none_stated | unreadable | not_captured | none_found

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("offer_status", sa.String(length=16), nullable=True), schema="prod")
    op.create_check_constraint(
        "ck_products_offer_status",
        "products",
        "offer_status IS NULL OR offer_status IN ('captured', 'none_stated', 'unreadable', 'not_captured', 'none_found')",
        schema="prod",
    )


def downgrade() -> None:
    op.drop_constraint("ck_products_offer_status", "products", schema="prod")
    op.drop_column("products", "offer_status", schema="prod")
