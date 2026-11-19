"""Offer tracker: which version's terms a check observed (owner 2026-11-19, DESIGN §27.16).

Some issuers show different terms on different visits ("Offers may vary"). campaign_checks.variant_version records
the version whose terms an observation matched, so terms seen again within 30 days are another observation of that
variant, not a new version. NULL for failed checks, manual checks and checks recorded before this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaign_checks", sa.Column("variant_version", sa.Integer()), schema="prod")


def downgrade() -> None:
    op.drop_column("campaign_checks", "variant_version", schema="prod")
