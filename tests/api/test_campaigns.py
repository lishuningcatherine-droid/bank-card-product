"""Campaign API (DESIGN §27.9) on PostgreSQL with the fictional Example Bank. Acceptance: no invented deadline or
countdown, assumptions shown with dollar figures, history labels only with enough history, sources/verification time
/status visible, demo data labelled."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest

from bankrec.tracker import config
from bankrec.tracker.sync import sync
from tests.integration.helpers import registry, run

pytestmark = [pytest.mark.db, pytest.mark.anyio]
CARDS = [
    {"card_key": "example_bank:everyday-cash", "bank_id": "example_bank",
     "canonical_key": "example_bank:credit_card:consumer:example bank everyday cash:-",
     "source_ids": ["example_bank:everyday-cash"], "series": "Everyday", "points_program": None},
    {"card_key": "example_bank:voyager-rewards", "bank_id": "example_bank",
     "canonical_key": "example_bank:credit_card:consumer:example bank voyager rewards:-",
     "source_ids": ["example_bank:voyager-rewards"], "series": "Voyager", "points_program": "example_points"},
]  # fmt: skip


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(session, settings, db_url, monkeypatch) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(config, "cards", lambda: CARDS)
    run(session, settings, registry())
    sync(session, datetime.now(UTC))
    session.commit()
    from bankrec.api.app import create_app

    app = create_app(
        settings.model_copy(update={"database_url": db_url, "web_origin": "http://localhost:3000"})
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_current_offers_without_a_profile(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/campaigns")
    assert r.status_code == 200
    body = r.json()
    names = {i["card"]["name"] for i in body["items"]}
    assert {"Example Bank Everyday Cash Card", "Example Bank Voyager Rewards Card"} <= names
    for i in body["items"]:
        # source, verification and status are always visible
        assert i["source_label"] and i["status_label"] and i["last_verified_at"] and i["terms"]["offer_url"]
        assert i["demo"] is True
        # no stated end date → no invented end and no countdown
        if i["terms"]["end"]["date"] is None:
            assert i["deadline_label"] == "Deadline unknown" and i["countdown_to"] is None
        # one record only → never a comparative label
        assert i["history"]["code"] == "insufficient_history"
    assert any("Eastern" in a for a in body["assumptions"])


async def test_points_and_cash_values_state_their_basis(client: httpx.AsyncClient) -> None:
    items = (await client.get("/api/v1/campaigns")).json()["items"]
    cash = next(i for i in items if i["card"]["card_key"] == "example_bank:everyday-cash")
    pts = next(i for i in items if i["card"]["card_key"] == "example_bank:voyager-rewards")
    assert cash["value"]["cents"] == 20000 and cash["value"]["assumption"] is None
    assert pts["terms"]["unit"] == "points" and pts["value"]["cents"] is None
    assert "No dollar value" in pts["value"]["assumption"]
    # the visitor's own value updates the comparison and says so
    mine = (await client.get("/api/v1/campaigns", params={"pv": "example_points:1.5"})).json()["items"]
    pts2 = next(i for i in mine if i["card"]["card_key"] == "example_bank:voyager-rewards")
    assert pts2["value"]["cents"] == round(pts["terms"]["total_amount"] * 1.5)
    assert "your own value" in pts2["value"]["assumption"]


async def test_filters_and_detail(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/api/v1/campaigns", params={"card": "example_bank:everyday-cash", "deadline": "unknown"}
    )
    [item] = r.json()["items"]
    d = (await client.get(f"/api/v1/campaigns/{item['id']}")).json()
    assert [v["version"] for v in d["versions"]] == [1]
    assert d["status_log"][0]["to_status"] == "active" and d["status_log"][0]["trigger"] == "auto"
    assert d["checks"] and d["checks"][0]["outcome"] == "seen"
    pc = (await client.get(f"/api/v1/products/{item['card']['product_id']}/campaigns")).json()
    assert [c["id"] for c in pc] == [item["id"]]
    assert (await client.get("/api/v1/campaigns/not-a-uuid")).status_code == 404
    assert (await client.get("/api/v1/campaigns", params={"pv": "bad value"})).status_code == 422


async def test_rules_and_point_values_are_public_with_sources(client: httpx.AsyncClient) -> None:
    rules = (await client.get("/api/v1/rules", params={"bank": "chase"})).json()
    by = {r["rule_key"]: r for r in rules}
    assert by["chase_5_24"]["source_type"] == "community" and by["chase_5_24"]["source_url"].startswith(
        "https://"
    )
    assert by["chase_sapphire_card"]["source_type"] == "official" and by["chase_sapphire_card"]["excerpt"]
    pv = {p["program"]: p for p in (await client.get("/api/v1/point-values")).json()}
    assert pv["chase_ur"]["floor_cents"] is None and pv["wf_rewards"]["floor_cents"] == 1.0
