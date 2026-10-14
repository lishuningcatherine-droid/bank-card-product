"""offers: window and holding period kept in their stated unit (count + unit); no month→day conversion

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNITS = "('days', 'weeks', 'months', 'years', 'billing_cycles')"


def upgrade() -> None:
    for col in ("qualification_window", "holding_period"):
        op.add_column("offers", sa.Column(f"{col}_count", sa.Integer(), nullable=True), schema="prod")
        op.add_column("offers", sa.Column(f"{col}_unit", sa.String(length=16), nullable=True), schema="prod")
        op.create_check_constraint(
            f"ck_offers_{col}_unit", "offers", f"{col}_unit IS NULL OR {col}_unit IN {_UNITS}", schema="prod"
        )
    # Existing rows: a window stored with months also carried a converted day count (months × 30). Keep the stated
    # months and drop the converted days; a days-only window is a stated day count.
    op.execute(
        "UPDATE prod.offers SET qualification_window_count = qualification_window_months, "
        "qualification_window_unit = 'months', qualification_window_days = NULL "
        "WHERE qualification_window_months IS NOT NULL"
    )
    op.execute(
        "UPDATE prod.offers SET qualification_window_count = qualification_window_days, "
        "qualification_window_unit = 'days' "
        "WHERE qualification_window_months IS NULL AND qualification_window_days IS NOT NULL"
    )


def downgrade() -> None:
    for col in ("qualification_window", "holding_period"):
        op.drop_constraint(f"ck_offers_{col}_unit", "offers", schema="prod")
        op.drop_column("offers", f"{col}_unit", schema="prod")
        op.drop_column("offers", f"{col}_count", schema="prod")
