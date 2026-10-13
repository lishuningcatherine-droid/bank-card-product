"""FastAPI application: public, read-only over ``prod`` (brief §12)."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from bankrec.api.repository import Filters, Repository
from bankrec.api.schemas import (
    BankSource,
    CompareRequest,
    CompareResponse,
    Health,
    HistoryEntry,
    OfferItem,
    OffersPage,
    Page,
    SourcesResponse,
)
from bankrec.api.security import (
    AccessLogMiddleware,
    BodyLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    problem,
)
from bankrec.db import prod as P
from bankrec.db.session import engine_for
from bankrec.recommend import recommend as run_recommend
from bankrec.recommend.common import DISCLAIMER
from bankrec.recommend.config import point_values, scoring
from bankrec.recommend.models import ProductView, RecommendRequest, RecommendResponse
from bankrec.settings import Settings, get_settings

log = logging.getLogger("bankrec.api")
COMPARE_ROWS = {
    "credit_card": [
        "annual_fee_cents",
        "intro_annual_fee_cents",
        "reward_currency",
        "base_rate",
        "foreign_tx_fee_pct",
        "purchase_apr_min_pct",
        "purchase_apr_max_pct",
        "intro_purchase_apr_months",
        "intro_bt_apr_months",
        "bt_fee_pct",
        "network",
        "segment",
        "is_co_branded",
        "is_student",
        "is_secured",
    ],
    "checking": [
        "monthly_fee_cents",
        "min_opening_deposit_cents",
        "fee_waivers",
        "overdraft_summary",
        "eligible_states",
        "access_model",
    ],
    "savings": [
        "apy_pct",
        "apy_tiers",
        "monthly_fee_cents",
        "min_opening_deposit_cents",
        "min_balance_cents",
        "withdrawal_restrictions",
        "eligible_states",
    ],
}


def create_app(settings: Settings | None = None) -> FastAPI:
    st = settings or get_settings()
    prod = st.env == "prod"
    app = FastAPI(
        title="Bank Product Recommendation API",
        version="1.0.0",
        debug=False,
        openapi_url="/api/v1/openapi.json",
        docs_url=None if prod else "/api/v1/docs",
        redoc_url=None,
        description="Public, read-only data about published, verified U.S. bank products. " + DISCLAIMER,
    )
    app.state.settings = st
    engine = engine_for(st.api_database_url or st.database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    app.add_middleware(SecurityHeadersMiddleware, hsts=prod)
    app.add_middleware(RateLimitMiddleware, per_minute=st.rate_limit_per_minute)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[st.web_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(AccessLogMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only — never the submitted values.
        errors = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg", "")} for e in exc.errors()]
        r = problem(422, "Invalid request", "Some inputs are out of range or missing.")
        r.body = r.render(
            {"type": "about:blank", "title": "Invalid request", "status": 422, "errors": errors}
        )
        r.headers["content-length"] = str(len(r.body))
        return r

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return problem(exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", extra={"error_type": type(exc).__name__})
        return problem(500, "Internal error", "Something went wrong. Please try again.")

    def session() -> Iterator[Session]:
        s = factory()
        try:
            yield s
        finally:
            s.rollback()
            s.close()

    def repo(s: Annotated[Session, Depends(session)]) -> Repository:
        return Repository(s, allow_test_only=st.allow_test_only)

    Repo = Annotated[Repository, Depends(repo)]

    def now() -> datetime:
        return datetime.now(UTC)

    prefix = "/api/v1"

    @app.get(prefix + "/health", response_model=Health, tags=["ops"])
    def health() -> Health:
        return Health(status="ok")

    @app.get(prefix + "/ready", tags=["ops"])
    def ready(s: Annotated[Session, Depends(session)]) -> dict[str, str]:
        try:
            s.execute(text("SELECT 1"))
            s.execute(select(P.Product.id).limit(1))
        except Exception as e:
            raise HTTPException(503, "database not ready") from e
        return {"status": "ready"}

    def _filters(
        type: str | None,
        bank: str | None,
        annual_fee_max: int | None,
        reward_category: str | None,
        has_bonus: bool | None,
        apy_min: Decimal | None,
        verified_since: datetime | None,
        segment: str | None,
        card_flags: str | None,
        q: str | None,
    ) -> Filters:
        flags = [f for f in (card_flags or "").split(",") if f]
        bad = [f for f in flags if f not in {"co_branded", "student", "secured", "business"}]
        if bad:
            raise HTTPException(422, f"unknown card flag(s): {', '.join(bad)}")
        return Filters(
            type=type,
            bank=bank,
            annual_fee_max=annual_fee_max,
            reward_category=reward_category,
            has_bonus=has_bonus,
            apy_min=apy_min,
            verified_since=verified_since,
            segment=segment,
            card_flags=flags,
            q=q,
        )

    TypeQ = Annotated[str | None, Query(pattern="^(credit_card|checking|savings)$")]
    BankQ = Annotated[str | None, Query(max_length=64, pattern="^[a-z0-9_]+$")]
    FeeQ = Annotated[int | None, Query(ge=0, le=1000, description="maximum annual fee in dollars")]
    CatQ = Annotated[str | None, Query(max_length=40, pattern="^[a-z_]+$")]
    ApyQ = Annotated[Decimal | None, Query(ge=0, le=15)]
    SegQ = Annotated[str | None, Query(pattern="^(consumer|business)$")]
    FlagsQ = Annotated[
        str | None, Query(max_length=60, description="comma list: co_branded,student,secured,business")
    ]
    TextQ = Annotated[str | None, Query(max_length=80)]
    PageQ = Annotated[int, Query(ge=1, le=1000)]
    SizeQ = Annotated[int, Query(ge=1, le=100)]

    @app.get(prefix + "/products", response_model=Page, tags=["products"])
    def products(
        r: Repo,
        type: TypeQ = None,
        bank: BankQ = None,
        annual_fee_max: FeeQ = None,
        reward_category: CatQ = None,
        has_bonus: bool | None = None,
        apy_min: ApyQ = None,
        verified_since: datetime | None = None,
        segment: SegQ = None,
        card_flags: FlagsQ = None,
        q: TextQ = None,
        page: PageQ = 1,
        page_size: SizeQ = 20,
    ) -> Page:
        f = _filters(
            type,
            bank,
            annual_fee_max,
            reward_category,
            has_bonus,
            apy_min,
            verified_since,
            segment,
            card_flags,
            q,
        )
        items, total = r.list_products(f, now(), page, page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def _typed(ptype: str) -> Any:
        def handler(
            r: Repo,
            bank: BankQ = None,
            annual_fee_max: FeeQ = None,
            reward_category: CatQ = None,
            has_bonus: bool | None = None,
            apy_min: ApyQ = None,
            verified_since: datetime | None = None,
            segment: SegQ = None,
            card_flags: FlagsQ = None,
            q: TextQ = None,
            page: PageQ = 1,
            page_size: SizeQ = 20,
        ) -> Page:
            f = _filters(
                ptype,
                bank,
                annual_fee_max,
                reward_category,
                has_bonus,
                apy_min,
                verified_since,
                segment,
                card_flags,
                q,
            )
            items, total = r.list_products(f, now(), page, page_size)
            return Page(items=items, total=total, page=page, page_size=page_size)

        return handler

    app.get(prefix + "/credit-cards", response_model=Page, tags=["products"], name="credit_cards")(
        _typed("credit_card")
    )
    app.get(prefix + "/checking-accounts", response_model=Page, tags=["products"], name="checking_accounts")(
        _typed("checking")
    )
    app.get(prefix + "/savings-accounts", response_model=Page, tags=["products"], name="savings_accounts")(
        _typed("savings")
    )

    @app.get(prefix + "/products/{product_id}", response_model=ProductView, tags=["products"])
    def product(product_id: str, r: Repo) -> ProductView:
        p = r.get(product_id, now())
        if p is None:
            raise HTTPException(404, "Product not found")
        return p

    @app.get(prefix + "/products/{product_id}/history", response_model=list[HistoryEntry], tags=["products"])
    def history(product_id: str, r: Repo) -> list[HistoryEntry]:
        if r.get(product_id, now()) is None:
            raise HTTPException(404, "Product not found")
        return [HistoryEntry(**h) for h in r.history(product_id)]

    @app.get(prefix + "/offers", response_model=OffersPage, tags=["offers"])
    def offers(
        r: Repo,
        type: TypeQ = None,
        bank: BankQ = None,
        include_inactive: Annotated[
            bool, Query(description="include expired/stale/recheck offers (labeled)")
        ] = False,
    ) -> OffersPage:
        items = []
        for p in r.list_products(Filters(type=type, bank=bank), now(), 1, 10_000)[0]:
            for o in p.offers:
                if include_inactive or o.state == "current":
                    items.append(
                        OfferItem(
                            product_id=p.id,
                            product_name=p.name,
                            bank_name=p.bank_name,
                            product_type=p.product_type,
                            offer=o,
                        )
                    )
        return OffersPage(items=items, total=len(items))

    @app.post(prefix + "/compare", response_model=CompareResponse, tags=["compare"])
    def compare(body: CompareRequest, r: Repo) -> CompareResponse:
        items, excluded = [], []
        for pid in dict.fromkeys(body.product_ids):
            p = r.get(pid, now())
            if p is None:
                raise HTTPException(404, "One or more products were not found")
            fee = p.details.get("annual_fee_cents")
            if (
                body.exclude_over_max_fee
                and body.max_annual_fee is not None
                and fee is not None
                and fee > body.max_annual_fee * 100
            ):
                excluded.append(
                    {"product_id": p.id, "name": p.name, "reason": "annual fee above your maximum"}
                )
                continue
            items.append(p)
        types = {p.product_type for p in items}
        rows = COMPARE_ROWS[next(iter(types))] if len(types) == 1 else []
        return CompareResponse(items=items, excluded=excluded, rows=rows, disclaimer=DISCLAIMER)

    @app.post(prefix + "/recommend", response_model=RecommendResponse, tags=["recommend"])
    def recommend(body: RecommendRequest, r: Repo) -> RecommendResponse:
        # Stateless: inputs are used for this computation only — never stored or logged.
        t = now()
        return run_recommend(r.all_of_type(body.product_type, t), body, t)

    @app.get(prefix + "/methodology", tags=["methodology"])
    def methodology() -> dict[str, Any]:
        from bankrec.freshness import config as fresh
        from bankrec.publish.changes import policy as change_policy
        from bankrec.validation.rules import policy as validation_policy

        vp = validation_policy()
        return {
            "scoring": scoring(),
            "point_values": point_values(),
            "freshness": fresh(),
            "change_policy": change_policy(),
            "validation": {
                "required": vp["required"],
                "key": vp["key"],
                "conditional": vp.get("conditional", {}),
            },
            "principles": [
                "Only Verified products and current, public, recently verified offers are recommended.",
                "A welcome bonus is never counted as recurring value.",
                "'Up to' and 'at least' offers add $0 to dollar estimates.",
                "Points are valued at the configured cents per point; portal-only rates are not monetized.",
                "Statement credits count only when you select them.",
                "No affiliate relationships; rankings are not paid.",
            ],
            "disclaimer": DISCLAIMER,
        }

    @app.get(prefix + "/sources", response_model=SourcesResponse, tags=["sources"])
    def sources(s: Annotated[Session, Depends(session)], r: Repo) -> SourcesResponse:
        from bankrec.registry.loader import load_registry

        reg = load_registry(include_test_only=st.allow_test_only, require_sources=False)
        summaries: dict[str, list[dict[str, Any]]] = {}
        for row in s.scalars(select(P.SourceSummary)):
            summaries.setdefault(row.bank_id, []).append(
                {
                    "product_type": row.product_type,
                    "last_run_at": row.last_run_at,
                    "sources_enabled": row.sources_enabled,
                    "requires_render": row.requires_render,
                    "status_counts": row.status_counts,
                }
            )
        counts: dict[str, dict[str, dict[str, int]]] = {}
        for p in r.list_products(Filters(), now(), 1, 100_000)[0]:
            c = counts.setdefault(p.bank_id, {}).setdefault(
                p.product_type, {"verified": 0, "partially_verified": 0}
            )
            c[p.label] += 1
        banks = []
        for b in reg.banks.values():
            if b.role != "bank":
                continue
            banks.append(
                BankSource(
                    bank_id=b.bank_id,
                    display_name=b.display_name,
                    official_domains=b.official_domains,
                    product_types={k.value: v.model_dump(mode="json") for k, v in b.product_types.items()},
                    known_limitations=b.known_limitations,
                    summary=summaries.get(b.bank_id, []),
                    published_counts=counts.get(b.bank_id, {}),
                )
            )
        cc = [
            {
                "name": b.display_name,
                "use": "Cross-check of APRs and fees only; never shown as current offers.",
            }
            for b in reg.banks.values()
            if b.role == "regulator"
        ]
        return SourcesResponse(
            banks=sorted(banks, key=lambda x: x.display_name),
            cross_check_sources=cc,
            notes=[
                "Data is checked on a schedule (APY every 12 hours, offers daily, other terms weekly), not continuously.",
                "Products appear only after their official pages are retrieved and verified.",
            ],
        )

    return app


app = create_app()
