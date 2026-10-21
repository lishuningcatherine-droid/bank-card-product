"""Anonymous ranking events, recorded only after the visitor opts in (owner decision 2026-10-19; DESIGN §26.7).

What is stored: a random id the browser created when the visitor opted in (not linked to anything else), the event,
the product type, the product and its position, the ordered list of products shown, which ranker ordered it, and the
hour it happened. What is never stored: questionnaire answers (raw or derived), IP addresses, user agents, cookies,
referrers or exact timestamps.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bankrec.db.base import AnalyticsBase

EVENTS = ("results_shown", "result_opened", "official_link_clicked", "compare_added")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class RankingEvent(AnalyticsBase):
    __tablename__ = "ranking_events"
    __table_args__ = (
        CheckConstraint("event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")", name="event"),
        CheckConstraint("product_type IN ('credit_card', 'checking', 'savings')", name="product_type"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    anon_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)  # one results view
    event: Mapped[str] = mapped_column(String(24))
    product_type: Mapped[str] = mapped_column(String(12))
    product_id: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)  # 1-based rank shown
    shown: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text)
    )  # results_shown: product ids in display order
    ranker: Mapped[str] = mapped_column(String(64))  # "baseline" or a model id
    occurred_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
