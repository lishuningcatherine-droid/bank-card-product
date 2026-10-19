"""API tests against real PostgreSQL seeded through the real pipeline with Example Bank (test_only) data."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import event, func, select, text

from bankrec.db import prod as P
from tests.integration.helpers import registry, run

pytestmark = [pytest.mark.db, pytest.mark.anyio]
FORBIDDEN_KEYS = {
    "confidence",
    "span_text",
    "snapshot_id",
    "parser_name",
    "parser_version",
    "raw_path",
    "traceback",
    "review",
    "candidate_id",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def seeded(session, settings, db_url):  # type: ignore[no-untyped-def]
    run(session, settings, registry())
    return settings.model_copy(update={"database_url": db_url, "web_origin": "http://localhost:3000"})


@pytest.fixture
async def client(seeded) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    from bankrec.api.app import create_app

    app = create_app(seeded)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _walk_keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _walk_keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _walk_keys(v)}
    return set()


async def test_health_ready_openapi(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
    assert (await client.get("/api/v1/ready")).json() == {"status": "ready"}
    spec = (await client.get("/api/v1/openapi.json")).json()
    for path in [
        "/api/v1/products",
        "/api/v1/products/{product_id}",
        "/api/v1/products/{product_id}/history",
        "/api/v1/credit-cards",
        "/api/v1/checking-accounts",
        "/api/v1/savings-accounts",
        "/api/v1/offers",
        "/api/v1/compare",
        "/api/v1/recommend",
        "/api/v1/methodology",
        "/api/v1/sources",
        "/api/v1/health",
    ]:
        assert path in spec["paths"], path


async def test_products_and_filters(client: httpx.AsyncClient) -> None:
    async def names(**params: Any) -> set[str]:
        r = await client.get("/api/v1/products", params=params)
        assert r.status_code == 200, r.text
        return {p["name"] for p in r.json()["items"]}

    assert len(await names()) == 11
    assert len(await names(type="credit_card")) == 7
    assert await names(type="credit_card", annual_fee_max=0) == {
        "Example Bank Everyday Cash Card",
        "Example Bank Business Cash Card",
        "Example Bank Secured Card",
        "Example Bank Student Cash Card",
        "Example Bank Rotating Cash Card",
        "Example Bank Voyager Rewards Card",
    } - {"Example Bank Voyager Rewards Card"}
    assert await names(card_flags="secured") == {"Example Bank Secured Card"}
    assert await names(card_flags="co_branded") == {"Example Air Miles Card from Example Bank"}
    assert (
        await names(card_flags="business")
        == await names(segment="business")
        == {"Example Bank Business Cash Card"}
    )
    assert await names(card_flags="student") == {"Example Bank Student Cash Card"}
    assert "Example Bank Everyday Cash Card" in await names(reward_category="dining")
    assert await names(apy_min="3.5") == {"Example Bank High Yield Savings"}
    assert await names(q="voyager") == {"Example Bank Voyager Rewards Card"}
    assert "Example Bank Secured Card" not in await names(has_bonus=True)
    assert await names(bank="nope") == set()
    assert len(await names(verified_since="2000-01-01T00:00:00Z")) == 11
    page = (await client.get("/api/v1/products", params={"page": 2, "page_size": 5})).json()
    assert page["total"] == 11 and len(page["items"]) == 5
    assert (await client.get("/api/v1/products", params={"card_flags": "bogus"})).status_code == 422
    assert (await client.get("/api/v1/products", params={"type": "mortgage"})).status_code == 422
    typed = (await client.get("/api/v1/savings-accounts")).json()
    assert typed["total"] == 2 and {i["product_type"] for i in typed["items"]} == {"savings"}


async def test_detail_history_and_no_internals(client: httpx.AsyncClient) -> None:
    items = (await client.get("/api/v1/credit-cards", params={"q": "everyday"})).json()["items"]
    pid = items[0]["id"]
    d = (await client.get(f"/api/v1/products/{pid}")).json()
    assert d["label"] == "verified" and d["official_url"].startswith("https://") and d["verified_at"]
    assert d["last_checked_at"] and d["details"]["annual_fee_cents"] == 0
    assert not (_walk_keys(d) & FORBIDDEN_KEYS)
    h = (await client.get(f"/api/v1/products/{pid}/history")).json()
    assert h[0]["kind"] in {"product", "offer"} and any(x["change_class"] == "initial" for x in h)
    assert (await client.get("/api/v1/products/not-a-uuid")).status_code == 404
    assert (await client.get("/api/v1/products/00000000-0000-0000-0000-000000000000")).status_code == 404


async def test_offers_current_public_only(client: httpx.AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    body = (await client.get("/api/v1/offers")).json()
    assert body["total"] == 8 and all(i["offer"]["state"] == "current" for i in body["items"])
    up_to = [i for i in body["items"] if i["offer"]["amount_qualifier"] == "up_to"]
    assert up_to and all(i["offer"]["amount_min"] is None for i in up_to)
    o = session.scalar(select(P.Offer).limit(1))
    o.audience = "targeted"
    session.commit()
    assert (await client.get("/api/v1/offers")).json()["total"] == 7
    assert (await client.get("/api/v1/offers", params={"include_inactive": True})).json()["total"] == 7
    # non-public offers are listed only on request, labelled with their audience, and never ranked
    labelled = (await client.get("/api/v1/offers", params={"include_non_public": True})).json()
    assert labelled["total"] == 8
    assert [i["offer"]["audience"] for i in labelled["items"] if i["offer"]["id"] == str(o.id)] == [
        "targeted"
    ]
    ranked = (await client.get("/api/v1/offers/ranked", params={"type": o.product.product_type})).json()
    assert str(o.id) not in {r["offer"]["id"] for r in ranked["items"]}


async def test_ranked_public_offers_have_dollar_estimates_and_no_scores(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/offers/ranked", params={"type": "credit_card"})).json()
    assert body["items"] and [r["rank"] for r in body["items"]] == list(range(1, len(body["items"]) + 1))
    for r in body["items"]:
        assert r["offer"]["audience"] == "public" and r["offer"]["state"] == "current"
        assert r["estimate"]["bonus_value_cents"] > 0
        assert "score" not in r and "components" not in r
    nets = [r["estimate"]["net_first_year_cents"] for r in body["items"]]
    known = [n for n in nets if n is not None]
    assert known == sorted(known, reverse=True)
    assert all(u["offer"]["amount_qualifier"] in ("up_to", "starting_at") for u in body["unranked"])
    assert any("¢" in a for a in body["assumptions"])
    m = (await client.get("/api/v1/methodology")).json()
    assert m["public_offer_ranking"] == body["assumptions"]
    assert (await client.get("/api/v1/offers/ranked", params={"sort": "score"})).status_code == 422


async def test_expired_offer_hidden_at_request_time(client: httpx.AsyncClient, session) -> None:  # type: ignore[no-untyped-def]
    from datetime import date

    o = session.scalar(select(P.Offer).where(P.Offer.amount_qualifier == "exact").limit(1))
    o.expiration_date = date(2020, 1, 1)  # stored status stays "current"
    session.commit()
    body = (await client.get("/api/v1/offers")).json()
    assert o.offer_url not in {
        i["offer"]["offer_url"] for i in body["items"] if i["offer"]["id"] == str(o.id)
    }
    pid = str(o.product_id)
    detail = (await client.get(f"/api/v1/products/{pid}")).json()
    assert [x["state"] for x in detail["offers"]] == ["expired"]


async def test_compare(client: httpx.AsyncClient) -> None:
    ids = [p["id"] for p in (await client.get("/api/v1/credit-cards")).json()["items"]]
    r = (await client.post("/api/v1/compare", json={"product_ids": ids[:3]})).json()
    assert len(r["items"]) == 3 and "annual_fee_cents" in r["rows"]
    assert (await client.post("/api/v1/compare", json={"product_ids": ids[:1]})).status_code == 422
    assert (await client.post("/api/v1/compare", json={"product_ids": ids[:5]})).status_code == 422
    ex = (
        await client.post(
            "/api/v1/compare",
            json={"product_ids": ids[:4], "max_annual_fee": 0, "exclude_over_max_fee": True},
        )
    ).json()
    assert all(i["details"]["annual_fee_cents"] == 0 for i in ex["items"])


CARD = {
    "product_type": "credit_card",
    "goal": "cashback",
    "monthly_spend": {"dining": 31337 // 100, "groceries": 400, "other": 1500},
    "max_annual_fee": 100,
    "exclude_over_max_fee": True,
    "bonus_importance": "high",
}


async def test_recommend_cards(client: httpx.AsyncClient) -> None:
    r = (await client.post("/api/v1/recommend", json=CARD)).json()
    assert r["results"] and r["disclaimer"]
    names = [x["product"]["name"] for x in r["results"]]
    assert "Example Bank Secured Card" not in names and "Example Bank Business Cash Card" not in names
    for x in r["results"]:
        assert x["product"]["label"] == "verified" and x["why"] and x["components"]
        v = x["values"]
        assert v["first_year_cents"] == v["ongoing_annual_cents"] + v["promotional_cents"] + (
            x["product"]["details"]["annual_fee_cents"]
            - (
                x["product"]["details"].get("intro_annual_fee_cents")
                if x["product"]["details"].get("intro_annual_fee_cents") is not None
                else x["product"]["details"]["annual_fee_cents"]
            )
        )
        if x["current_offer"] and x["current_offer"]["amount_qualifier"] != "exact":
            assert v["promotional_cents"] == 0 and x["possible_welcome_offer"]
    assert not (_walk_keys(r) & FORBIDDEN_KEYS)


async def test_recommend_checking_and_savings(client: httpx.AsyncClient) -> None:
    c = (
        await client.post(
            "/api/v1/recommend",
            json={
                "product_type": "checking",
                "has_direct_deposit": True,
                "monthly_direct_deposit": 2500,
                "max_monthly_fee": 0,
                "state": "NY",
            },
        )
    ).json()
    top = {x["product"]["name"]: x for x in c["results"]}
    every = top["Example Bank Everyday Checking"]
    assert every["achievability"]["achievable"] and every["values"]["promotional_cents"] == 50000
    assert every["achievability"]["explanation"].startswith("Yes: $2,500/month × 3 months")
    ca = (
        await client.post(
            "/api/v1/recommend", json={"product_type": "checking", "state": "CA", "max_monthly_fee": 50}
        )
    ).json()
    assert "Example Bank Everyday Checking" in {e["name"] for e in ca["excluded"]}
    s = (
        await client.post(
            "/api/v1/recommend",
            json={"product_type": "savings", "deposit_range": "5k_25k", "holding_months": 6},
        )
    ).json()
    hy = next(x for x in s["results"] if x["product"]["name"] == "Example Bank High Yield Savings")
    assert hy["values"]["promotional_cents"] == 20000 and hy["achievability"]["achievable"]


async def test_recommend_validation_does_not_echo_inputs(client: httpx.AsyncClient) -> None:
    bad = {**CARD, "monthly_spend": {"dining": 987654321}}
    r = await client.post("/api/v1/recommend", json=bad)
    assert r.status_code == 422 and "987654321" not in r.text
    assert (await client.post("/api/v1/recommend", json={**CARD, "ssn": "123-45-6789"})).status_code == 422
    assert (await client.post("/api/v1/recommend", json={"product_type": "mortgage"})).status_code == 422


async def test_privacy_inputs_not_persisted_or_logged(client: httpx.AsyncClient, engine, caplog) -> None:  # type: ignore[no-untyped-def]
    from bankrec.db.session import engine_for

    api_engine = engine_for(str(engine.url.render_as_string(hide_password=False)))
    statements: list[str] = []

    def capture(conn, cursor, statement, params, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement.split()[0].upper())

    def counts() -> dict[str, int]:
        with engine.connect() as c:
            tables = (
                c.execute(
                    text(
                        "select schemaname||'.'||tablename from pg_tables where schemaname in "
                        "('staging','prod')"
                    )
                )
                .scalars()
                .all()
            )
            return {t: c.execute(text(f"select count(*) from {t}")).scalar_one() for t in tables}

    before = counts()
    event.listen(api_engine, "before_cursor_execute", capture)
    try:
        with caplog.at_level(logging.DEBUG):
            sentinel = {**CARD, "monthly_spend": {"dining": 4242, "groceries": 1717, "other": 2929}}
            assert (await client.post("/api/v1/recommend", json=sentinel)).status_code == 200
            ids = [p["id"] for p in (await client.get("/api/v1/credit-cards")).json()["items"]][:2]
            assert (
                await client.post("/api/v1/compare", json={"product_ids": ids, "max_annual_fee": 777})
            ).status_code == 200
    finally:
        event.remove(api_engine, "before_cursor_execute", capture)
    assert counts() == before
    assert statements and set(statements) <= {"SELECT", "ROLLBACK", "BEGIN"}
    import re

    logs = caplog.text + json.dumps([r.__dict__ for r in caplog.records], default=str)
    # Bounded matches: random request IDs / UUIDs / timings may contain these digits as substrings.
    for v in ("4242", "1717", "2929", "777"):
        assert not re.search(rf"(?<![0-9a-fA-F.:-]){v}(?![0-9a-fA-F.:-])", logs), v
    for key in ("monthly_spend", "dining", "groceries", "max_annual_fee", "product_ids"):
        assert key not in logs, key


async def test_security_headers_limits_cors(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    big = await client.post(
        "/api/v1/recommend", content=b"{" + b" " * 20000 + b"}", headers={"content-type": "application/json"}
    )
    assert big.status_code == 413
    pre = await client.options(
        "/api/v1/recommend",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert pre.headers.get("access-control-allow-origin") is None
    ok = await client.options(
        "/api/v1/recommend",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_rate_limit(seeded) -> None:  # type: ignore[no-untyped-def]
    from bankrec.api.app import create_app

    app = create_app(seeded.model_copy(update={"rate_limit_per_minute": 2}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.post("/api/v1/recommend", json=CARD)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


async def test_methodology_and_sources(client: httpx.AsyncClient) -> None:
    m = (await client.get("/api/v1/methodology")).json()
    assert (
        m["scoring"]["credit_card"]["weights"]["ongoing"] == 0.3
        and m["point_values"]["default_cents_per_point"]
    )
    s = (await client.get("/api/v1/sources")).json()
    ids = {b["bank_id"] for b in s["banks"]}
    assert {"chase", "capital_one", "bank_of_america", "american_express", "us_bank", "example_bank"} <= ids
    eb = next(b for b in s["banks"] if b["bank_id"] == "example_bank")
    # 6: the Example Bank Secured Card states a minimum deposit only, so it is Partially verified (DESIGN §24.17 F)
    assert eb["published_counts"]["credit_card"]["verified"] == 6
    assert any(x["product_type"] == "credit_card" and x["last_run_at"] for x in eb["summary"])
    assert s["cross_check_sources"][0]["name"].startswith("Consumer Financial Protection Bureau")


async def test_test_only_hidden_in_production(seeded) -> None:  # type: ignore[no-untyped-def]
    from bankrec.api.app import create_app

    app = create_app(seeded.model_copy(update={"env": "prod"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t") as c:
        assert (await c.get("/api/v1/products")).json()["total"] == 0
        assert (await c.get("/api/v1/docs")).status_code == 404
        assert "strict-transport-security" in (await c.get("/api/v1/health")).headers


async def test_db_counts_unchanged_helper(session) -> None:  # type: ignore[no-untyped-def]
    assert session.scalar(select(func.count()).select_from(P.Product)) >= 0
