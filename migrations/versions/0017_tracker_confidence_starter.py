"""Offer tracker: rule confidence and starter cards (owner 2026-11-10, DESIGN §27.4, §27.1).

application_rules.confidence: for community rules, how widely the rule is corroborated — strong (a met rule means
"not a fit for now") or weak (a met rule means "confirm first"). NULL for the issuer's own rules.
tracked_cards.starter: student | secured for cards meant for people with little or no credit history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("application_rules", sa.Column("confidence", sa.String(8)), schema="prod")
    op.create_check_constraint(
        "ck_application_rules_confidence", "application_rules",
        "confidence IS NULL OR confidence IN ('strong', 'weak')", schema="prod",
    )  # fmt: skip
    op.add_column("tracked_cards", sa.Column("starter", sa.String(10)), schema="prod")


def downgrade() -> None:
    op.drop_column("tracked_cards", "starter", schema="prod")
    op.drop_constraint("ck_application_rules_confidence", "application_rules", schema="prod")
    op.drop_column("application_rules", "confidence", schema="prod")
