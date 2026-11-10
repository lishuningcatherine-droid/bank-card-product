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

from bankrec import events as ev
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
from bankrec.rank.rankers import active_ranker
from bankrec.recommend import recommend as run_recommend
from bankrec.recommend.common import DISCLAIMER, FACTORS
from bankrec.recommend.config import point_values
from bankrec.recommend.models import ProductView, RecommendRequest, RecommendResponse
from bankrec.recommend.public_offers import Group, PublicOffersResponse, Sort, ranking_assumptions
from bankrec.recommend.public_offers import rank as rank_public_offers
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

    @app.get(prefix + "/offers/ranked", response_model=PublicOffersResponse, tags=["offers"])
    def ranked_offers(
        r: Repo,
        type: Annotated[str, Query(pattern="^(credit_card|checking|savings)$")] = "credit_card",
        sort: Annotated[Sort, Query(description="value | bonus | requirement | ending")] = "value",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        group: Annotated[
            Group, Query(description="cash | points (ranked separately, DESIGN §26.4)")
        ] = "cash",
    ) -> PublicOffersResponse:
        """Public offers of Verified products ranked by a dollar estimate (no user inputs; DESIGN §25.3)."""
        t = now()
        return rank_public_offers(r.all_of_type(type, t), type, sort, t, limit, group)

    @app.get(prefix + "/offers", response_model=OffersPage, tags=["offers"])
    def offers(
        r: Repo,
        type: TypeQ = None,
        bank: BankQ = None,
        include_inactive: Annotated[
            bool, Query(description="include expired/stale/recheck offers (labeled)")
        ] = False,
        include_non_public: Annotated[
            bool,
            Query(description="include targeted, referral and pre-approved offers (labeled by audience)"),
        ] = False,
    ) -> OffersPage:
        items = []
        for p in r.list_products(Filters(type=type, bank=bank), now(), 1, 10_000)[0]:
            for o in p.offers:
                if (include_inactive or o.state == "current") and (
                    include_non_public or o.audience == "public"
                ):
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
        # the deterministic baseline, re-ordered only by a ranking model that passed every gate (DESIGN §26.8)
        return active_ranker().rerank(run_recommend(r.all_of_type(body.product_type, t), body, t))

    @app.get(prefix + "/methodology", tags=["methodology"])
    def methodology() -> dict[str, Any]:
        from bankrec.freshness import config as fresh
        from bankrec.publish.changes import policy as change_policy
        from bankrec.validation.rules import policy as validation_policy

        vp = validation_policy()
        return {
            # what the recommendations consider, in words; weights and scores are never published (DESIGN §26.6)
            "factors": FACTORS,
            "point_values": point_values(),
            "public_offer_ranking": ranking_assumptions(),
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

    # ---- consented, anonymous ranking events (DESIGN §26.7)
    @app.get(prefix + "/events/config", tags=["events"])
    def events_config() -> dict[str, Any]:
        return {
            "enabled": st.event_logging_enabled,
            "retention_days": st.event_retention_days,
            "stored": ev.STORED,
            "never_stored": ev.NEVER_STORED,
        }

    @app.post(prefix + "/events", status_code=204, tags=["events"])
    def record_event(body: ev.EventIn, s: Annotated[Session, Depends(session)]) -> None:
        if not st.event_logging_enabled:
            raise HTTPException(404, "Not found")
        ev.record(s, body, now())
        s.commit()

    @app.post(prefix + "/events/delete", tags=["events"])
    def delete_events(body: ev.DeleteIn, s: Annotated[Session, Depends(session)]) -> dict[str, int]:
        """Deletes every event recorded under this anonymous id. Always available, even when logging is off."""
        n = ev.delete_for(s, body.anon_id)
        s.commit()
        return {"deleted": n}

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

    # ------------------------------------------------------------------ offer tracker (DESIGN §27.9)
    from bankrec.tracker import views as TV

    PvQ = Annotated[
        str | None,
        Query(
            max_length=300,
            pattern=r"^[a-z0-9_]+:\d{1,2}(\.\d{1,3})?(,[a-z0-9_]+:\d{1,2}(\.\d{1,3})?)*$",
            description="your own cents per point, per program: chase_ur:1.25,amex_mr:1.0",
        ),
    ]

    def _pv(pv: str | None) -> dict[str, float]:
        return {k: float(v) for k, v in (x.split(":") for x in pv.split(","))} if pv else {}

    def _builder(s: Session, pv: str | None = None) -> TV.Builder:
        return TV.Builder(s, allow_demo=st.allow_test_only, overrides=_pv(pv))

    @app.get(prefix + "/campaigns", response_model=TV.CampaignPage, tags=["campaigns"])
    def campaigns(
        s: Annotated[Session, Depends(session)],
        bank: BankQ = None,
        card: Annotated[str | None, Query(max_length=80, pattern=r"^[a-z0-9_]+:[a-z0-9-]+$")] = None,
        segment: SegQ = None,
        offer_type: Annotated[
            str | None,
            Query(pattern="^(welcome_bonus|spend_multiplier|first_year_fee|first_year_match|other)$"),
        ] = None,
        channel: Annotated[str | None, Query(pattern="^(public|targeted|referral|branch)$")] = None,
        annual_fee_max: FeeQ = None,
        min_spend_max: Annotated[int | None, Query(ge=0, le=100_000, description="dollars")] = None,
        deadline: Annotated[
            str | None, Query(pattern="^(known|unknown|within_30)$", description="deadline filter")
        ] = None,
        include_past: Annotated[bool, Query(description="include expired and withdrawn campaigns")] = False,
        sort: Annotated[str, Query(pattern="^(recent|deadline|value|spend)$")] = "recent",
        pv: PvQ = None,
    ) -> TV.CampaignPage:
        """Current offer campaigns of the tracked cards, no personal data needed (DESIGN §27.9)."""
        b, t = _builder(s, pv), now()
        items = [b.view(c, t) for c in b.campaigns()]
        keep = []
        for v in items:
            if not include_past and v.status not in TV.CURRENT:
                continue
            if (bank and v.card.bank_id != bank) or (card and v.card.card_key != card):
                continue
            if (segment and v.card.segment != segment) or (offer_type and v.offer_type != offer_type):
                continue
            if channel and v.channel != channel:
                continue
            if annual_fee_max is not None and (
                v.card.annual_fee_cents is None or v.card.annual_fee_cents > annual_fee_max * 100
            ):
                continue
            if min_spend_max is not None and (v.terms.min_spend_cents or 0) > min_spend_max * 100:
                continue
            if (deadline == "known" and not v.terms.end.date) or (deadline == "unknown" and v.terms.end.date):
                continue
            if deadline == "within_30" and not (
                v.terms.end.date
                and v.terms.end.confirmed
                and (datetime.fromisoformat(v.terms.end.date).date() - t.date()).days <= 30
            ):
                continue
            keep.append(v)
        key = {
            "recent": lambda v: -(v.last_verified_at or v.first_seen_at).timestamp(),
            "deadline": lambda v: (v.terms.end.date is None, v.terms.end.date or ""),
            "value": lambda v: (v.value.cents is None, -(v.value.cents or 0)),
            "spend": lambda v: (v.terms.min_spend_cents is None, v.terms.min_spend_cents or 0),
        }[sort]
        keep.sort(key=key)
        return TV.CampaignPage(items=keep, total=len(keep), assumptions=TV.assumptions())

    @app.get(prefix + "/campaigns/{campaign_id}", response_model=TV.CampaignDetail, tags=["campaigns"])
    def campaign(
        campaign_id: str, s: Annotated[Session, Depends(session)], pv: PvQ = None
    ) -> TV.CampaignDetail:
        try:
            c = s.get(P.Campaign, campaign_id)
        except Exception as e:  # malformed UUID
            raise HTTPException(404, "Campaign not found") from e
        if c is None or (c.demo and not st.allow_test_only):
            raise HTTPException(404, "Campaign not found")
        return _builder(s, pv).detail(c, now())

    @app.get(
        prefix + "/products/{product_id}/campaigns", response_model=list[TV.CampaignView], tags=["campaigns"]
    )
    def product_campaigns(
        product_id: str, s: Annotated[Session, Depends(session)], pv: PvQ = None
    ) -> list[TV.CampaignView]:
        """Every campaign of a tracked card, current and past (newest first)."""
        b, t = _builder(s, pv), now()
        out = [b.view(c, t) for c in b.campaigns() if b.card(c.card_key).product_id == product_id]
        return sorted(out, key=lambda v: v.first_seen_at, reverse=True)

    @app.get(prefix + "/rules", response_model=list[TV.RuleView], tags=["campaigns"])
    def rules(s: Annotated[Session, Depends(session)], bank: BankQ = None) -> list[TV.RuleView]:
        q = select(P.ApplicationRule).order_by(P.ApplicationRule.bank_id, P.ApplicationRule.rule_key)
        if bank:
            q = q.where(P.ApplicationRule.bank_id == bank)
        return [TV.rule_view(r) for r in s.scalars(q)]

    @app.get(prefix + "/point-values", response_model=list[TV.PointValue], tags=["campaigns"])
    def point_value_floors() -> list[TV.PointValue]:
        return TV.point_values()

    return app


app = create_app()
