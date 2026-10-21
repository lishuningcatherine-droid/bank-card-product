"""Consented, anonymous ranking events (DESIGN §26.7): record, delete on request, purge after the retention."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session

from bankrec.db.analytics import RankingEvent

ProductId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]

STORED = [
    "a random id your browser creates when you opt in (not linked to you or to anything else)",
    "which kind of product you looked at (credit card, checking or savings)",
    "the products shown, in order, and which one you opened or followed to the bank",
    "the hour it happened",
]
NEVER_STORED = [
    "your answers to the questions, in any form",
    "your IP address, browser or device details",
    "cookies, referrers or exact times",
]


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: Literal[True]  # sent only by a browser whose visitor opted in
    anon_id: uuid.UUID
    list_id: uuid.UUID
    event: Literal["results_shown", "result_opened", "official_link_clicked", "compare_added"]
    product_type: Literal["credit_card", "checking", "savings"]
    product_id: ProductId | None = None
    position: Annotated[int, Field(ge=1, le=100)] | None = None
    shown: Annotated[list[ProductId], Field(max_length=50)] | None = None
    ranker: Annotated[str, Field(max_length=64, pattern=r"^[a-z0-9_.:-]+$")] = "baseline"

    @model_validator(mode="after")
    def _shape(self) -> EventIn:
        if self.event == "results_shown":
            if not self.shown or self.product_id is not None or self.position is not None:
                raise ValueError("results_shown carries the list shown and no single product")
        elif self.product_id is None or self.position is None or self.shown is not None:
            raise ValueError("a product event carries the product and its position")
        return self


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anon_id: uuid.UUID


def hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def record(session: Session, e: EventIn, now: datetime) -> None:
    session.add(
        RankingEvent(
            anon_id=e.anon_id,
            list_id=e.list_id,
            event=e.event,
            product_type=e.product_type,
            product_id=e.product_id,
            position=e.position,
            shown=e.shown,
            ranker=e.ranker,
            occurred_hour=hour(now),
        )
    )


def delete_for(session: Session, anon_id: uuid.UUID) -> int:
    res = session.execute(delete(RankingEvent).where(RankingEvent.anon_id == anon_id))
    return int(getattr(res, "rowcount", 0) or 0)


def purge(session: Session, now: datetime, retention_days: int) -> int:
    res = session.execute(
        delete(RankingEvent).where(RankingEvent.occurred_hour < now - timedelta(days=retention_days))
    )
    return int(getattr(res, "rowcount", 0) or 0)
