"""Consented, anonymous ranking events (DESIGN §26.7). Example Bank data only."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, text

from bankrec.db.analytics import RankingEvent
from tests.api.test_api import seeded  # noqa: F401  (fixture)

pytestmark = [pytest.mark.db, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _client(settings) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    from bankrec.api.app import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://t"
    ) as c:
        yield c


@pytest.fixture
async def on(seeded) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]  # noqa: F811
    async for c in _client(seeded.model_copy(update={"event_logging_enabled": True})):
        yield c


@pytest.fixture
async def off(seeded) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]  # noqa: F811
    async for c in _client(seeded):
        yield c


def shown(anon: uuid.UUID, lid: uuid.UUID, **kw: object) -> dict[str, object]:
    return {
        "consent": True,
        "anon_id": str(anon),
        "list_id": str(lid),
        "event": "results_shown",
        "product_type": "credit_card",
        "shown": ["p1", "p2", "p3"],
        **kw,
    }


async def test_logging_is_off_by_default(off: httpx.AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    cfg = (await off.get("/api/v1/events/config")).json()
    assert cfg["enabled"] is False and cfg["never_stored"]
    r = await off.post("/api/v1/events", json=shown(uuid.uuid4(), uuid.uuid4()))
    assert r.status_code == 404
    assert session.scalar(select(func.count()).select_from(RankingEvent)) == 0


async def test_events_need_consent_and_carry_no_answers(on: httpx.AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    anon, lid = uuid.uuid4(), uuid.uuid4()
    assert (await on.post("/api/v1/events", json=shown(anon, lid, consent=False))).status_code == 422
    # anything beyond the documented fields (e.g. an answer) is refused, not silently dropped
    assert (
        await on.post("/api/v1/events", json=shown(anon, lid, monthly_spend={"dining": 400}))
    ).status_code == 422
    assert (await on.post("/api/v1/events", json=shown(anon, lid))).status_code == 204
    click = {
        "consent": True,
        "anon_id": str(anon),
        "list_id": str(lid),
        "event": "official_link_clicked",
        "product_type": "credit_card",
        "product_id": "p2",
        "position": 2,
    }
    assert (await on.post("/api/v1/events", json=click)).status_code == 204
    assert (await on.post("/api/v1/events", json={**click, "position": None})).status_code == 422
    rows = session.scalars(select(RankingEvent).order_by(RankingEvent.event)).all()
    assert [(r.event, r.position, r.shown) for r in rows] == [
        ("official_link_clicked", 2, None),
        ("results_shown", None, ["p1", "p2", "p3"]),
    ]
    assert all(r.occurred_hour.minute == 0 and r.occurred_hour.second == 0 for r in rows)
    cols = set(session.execute(text("select * from analytics.ranking_events limit 0")).keys())
    assert cols == {
        "id",
        "anon_id",
        "list_id",
        "event",
        "product_type",
        "product_id",
        "position",
        "shown",
        "ranker",
        "occurred_hour",
    }


async def test_delete_my_data_and_retention_purge(
    on: httpx.AsyncClient, off: httpx.AsyncClient, session
) -> None:  # type: ignore[no-untyped-def]
    from bankrec import events as ev

    mine, other = uuid.uuid4(), uuid.uuid4()
    for a in (mine, mine, other):
        assert (await on.post("/api/v1/events", json=shown(a, uuid.uuid4()))).status_code == 204
    # deleting works even after the operator turns logging off
    assert (await off.post("/api/v1/events/delete", json={"anon_id": str(mine)})).json() == {"deleted": 2}
    assert session.scalar(select(func.count()).select_from(RankingEvent)) == 1
    session.expire_all()
    assert ev.purge(session, datetime.now(UTC) + timedelta(days=181), 180) == 1
    session.commit()
    assert session.scalar(select(func.count()).select_from(RankingEvent)) == 0


async def test_recommend_response_names_its_ranker(on: httpx.AsyncClient) -> None:
    from tests.api.test_api import CARD

    assert (await on.post("/api/v1/recommend", json=CARD)).json()["ranker"] == "baseline"
