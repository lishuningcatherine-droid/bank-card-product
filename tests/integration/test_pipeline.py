"""End-to-end pipeline against real PostgreSQL with synthetic Example Bank pages."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl
from sqlalchemy import func, select

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.failures import Failure
from tests.integration.helpers import FIX, mutate, registry, run, source

pytestmark = pytest.mark.db


def _product(session, name: str) -> P.Product:  # type: ignore[no-untyped-def]
    return session.scalar(select(P.Product).where(P.Product.official_name == name))


def test_first_run_publishes_with_provenance(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    r = run(session, settings, reg)
    assert {o.terminal for o in r.sources} == {"published"}
    assert len(r.sources) == len(reg.enabled())
    products = list(session.scalars(select(P.Product)))
    assert len(products) == 11
    assert all(
        p.official_name.lower() != "unknown" and p.official_url.startswith("https://") for p in products
    )
    # every non-null published detail field has provenance with a snapshot and a span
    for p in products:
        prov = {
            f.field_path: f
            for f in session.scalars(
                select(P.FieldProvenance).where(
                    P.FieldProvenance.product_id == p.id, P.FieldProvenance.offer_id.is_(None)
                )
            )
        }
        detail = p.card or p.checking or p.savings
        for col in (c.name for c in detail.__table__.columns):
            v = getattr(detail, col)
            if (
                col == "product_id"
                or v is None
                or (col in {"is_co_branded", "is_student", "is_secured"} and not v)
            ):
                continue
            assert (
                col in prov and prov[col].span_text and prov[col].snapshot_id and prov[col].parser_version
            ), (p.official_name, col)
    offers = list(session.scalars(select(P.Offer)))
    assert offers and all(
        o.capture_conditions and o.capture_conditions["capture_context"] == "public_default" for o in offers
    )
    up_to = [o for o in offers if o.amount_qualifier == "up_to"]
    assert up_to and all(o.amount_min is None for o in up_to)
    assert session.scalar(select(func.count()).select_from(P.ProductVersion)) == 11
    assert session.scalar(select(func.count()).select_from(S.RevalidationOutbox)) > 0
    snaps = list(session.scalars(select(S.PageSnapshot)))
    assert len(snaps) == 11
    assert all(x.page_type == "official_product_detail" and x.classifier_signals for x in snaps)


def test_second_run_unchanged_only_updates_checked(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    before = {p.id: p.last_confirmed_at for p in session.scalars(select(P.Product))}
    r = run(session, settings, reg)
    assert {o.terminal for o in r.sources} == {"unchanged"}
    session.expire_all()
    for p in session.scalars(select(P.Product)):
        assert p.last_confirmed_at >= before[p.id]
    assert session.scalar(select(func.count()).select_from(P.ProductVersion)) == 11
    assert (
        session.scalar(select(func.count()).select_from(S.PageCheck).where(S.PageCheck.result == "unchanged"))
        == 11
    )


def test_minor_apy_change_auto_publishes_new_version(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    f = mutate(tmp_path, "savings_high_yield.html", "4.00% APY", "4.20% APY")
    r = run(session, settings, reg, [source(reg, "high-yield", f)])
    assert r.products[0].decision == "published_version"
    p = _product(session, "Example Bank High Yield Savings")
    assert p.savings.apy_pct == Decimal("4.20") and p.current_version == 2 and not p.recheck_pending
    v2 = session.scalar(
        select(P.ProductVersion).where(P.ProductVersion.product_id == p.id, P.ProductVersion.version == 2)
    )
    assert v2.change_class == "minor" and v2.change_summary[0]["field"] == "apy_pct"
    v1 = session.scalar(
        select(P.ProductVersion).where(P.ProductVersion.product_id == p.id, P.ProductVersion.version == 1)
    )
    assert v1.valid_to is not None and p.last_changed_at is not None


def test_major_changes_go_to_review_and_old_value_stays(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    f = mutate(tmp_path, "savings_high_yield.html", "4.00% APY", "4.50% APY")
    r = run(session, settings, reg, [source(reg, "high-yield", f)])
    assert r.products[0].decision == "review"
    p = _product(session, "Example Bank High Yield Savings")
    assert p.savings.apy_pct == Decimal("4.00") and p.recheck_pending and p.recheck_reason == "major_change"
    item = session.scalar(select(S.ManualReviewItem).where(S.ManualReviewItem.reason_code == "major_change"))
    assert item is not None and item.context["changes"][0]["field"] == "apy_pct"
    # annual fee change on a card
    g = mutate(
        tmp_path,
        "card_everyday_cash.html",
        "<th>Annual Fee</th><td>$0</td>",
        "<th>Annual Fee</th><td>$39</td>",
    )
    run(session, settings, reg, [source(reg, "everyday-cash", g)])
    c = _product(session, "Example Bank Everyday Cash Card")
    assert c.card.annual_fee_cents == 0 and c.recheck_pending and "annual_fee_cents" in c.recheck_fields


def test_offer_disappeared_and_new_offer_need_review(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    html = (FIX / "card_student_cash.html").read_text()
    s, e = html.index('<section class="offer">'), html.index("</section>") + len("</section>")
    gone = tmp_path / "student.html"
    gone.write_text(html[:s] + html[e:])
    run(session, settings, reg, [source(reg, "student-cash", gone)])
    p = _product(session, "Example Bank Student Cash Card")
    assert [o.status for o in p.offers] == ["recheck_pending"] and p.recheck_pending
    added = mutate(
        tmp_path,
        "checking_online_checking.html",
        "<p>Account type: Online-only checking</p>",
        '<p>Account type: Online-only checking</p><section class="offer"><p class="offer-headline">'
        "Earn a $100 bonus with direct deposits totaling $1,000 within 60 days.</p></section>",
    )
    r = run(session, settings, reg, [source(reg, "online-checking", added)])
    assert r.products[0].decision == "review"
    q = _product(session, "Example Bank Online Checking")
    assert q.offers == [] and q.recheck_pending
    assert any(c["rule"] == "offer_appeared" for c in r.products[0].changes)


def test_parser_regression_alerts_downgrades_and_resolves(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    sent: list[httpx.Request] = []
    settings = settings.model_copy(
        update={"alert_webhook_url": "https://hooks.example.invalid/x", "alert_webhook_secret": "s3cret"}
    )
    import bankrec.alerts as alerts

    real = alerts._send

    def fake_send(st, payload, client):  # type: ignore[no-untyped-def]
        return real(
            st,
            payload,
            httpx.Client(
                transport=httpx.MockTransport(lambda req: (sent.append(req), httpx.Response(200))[1])
            ),
        )

    alerts._send = fake_send
    try:
        reg = registry()
        run(session, settings, reg)
        # the page still shows its fee section (so the capture passes the quality gate) but the parser cannot read it
        unread = "<tr><th>Fees</th><td>See the annual fee schedule</td></tr>"
        broken = mutate(tmp_path, "card_secured.html", "<tr><th>Annual Fee</th><td>$0</td></tr>", unread)
        r = run(session, settings, reg, [source(reg, "secured", broken)])
        assert r.alerts and r.alerts[0]["kind"].startswith("fields_lost") and r.alerts[0]["new_incident"]
        p = _product(session, "Example Bank Secured Card")
        assert p.recheck_pending and p.recheck_reason == "parser_failure"
        alert = session.scalar(select(S.Alert))
        assert alert.state == "open" and alert.webhook_open_sent
        body = json.loads(sent[0].content)
        assert body["event"] == "parser_regression" and sent[0].headers["X-Bankrec-Signature"].startswith(
            "t="
        )
        # same failure again: no second incident
        broken2 = mutate(
            tmp_path,
            "card_secured.html",
            "<tr><th>Annual Fee</th><td>$0</td></tr>",
            unread + "<!-- v2 -->",
            name="secured2.html",
        )
        r2 = run(session, settings, reg, [source(reg, "secured", broken2)])
        assert session.scalar(select(func.count()).select_from(S.Alert)) == 1
        assert not r2.alerts or not r2.alerts[0]["new_incident"]
        # good parse resolves
        run(session, settings, reg, [source(reg, "secured")])
        session.expire_all()
        assert session.scalar(select(S.Alert)).state == "resolved"
        assert not _product(session, "Example Bank Secured Card").recheck_pending
        assert json.loads(sent[-1].content)["event"] == "parser_regression_resolved"
    finally:
        alerts._send = real


def test_placeholder_apy_is_requires_render(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    r = run(session, settings, reg, [source(reg, "high-yield", FIX / "pages" / "savings_static_nan.html")])
    assert r.sources[0].terminal == "needs_review"
    assert _product(session, "Example Bank High Yield Savings") is None
    prov = session.scalar(
        select(S.FieldProvenanceStaging).where(S.FieldProvenanceStaging.field_path == "apy_pct")
    )
    assert prov.null_reason == "requires_render" and prov.value is None


@pytest.mark.parametrize(
    ("page", "failure"),
    [
        ("blocked.html", Failure.BOT_CHALLENGE),
        ("empty.html", Failure.EMPTY_PAGE),
        ("login.html", Failure.LOGIN_WALL),
    ],
)
def test_failed_pages_never_create_products(session, settings, page, failure) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    r = run(session, settings, reg, [source(reg, "everyday-cash", FIX / "pages" / page)])
    o = r.sources[0]
    assert o.terminal == "retrieval_failed" and o.failure is failure and o.next_action
    assert session.scalar(select(func.count()).select_from(P.Product)) == 0
    assert session.scalar(select(func.count()).select_from(S.DuplicateCandidate)) == 0


def test_non_product_pages_rejected(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    r = run(
        session,
        settings,
        reg,
        [
            source(reg, "everyday-cash", FIX / "pages" / "marketing.html"),
            source(reg, "voyager-rewards", FIX / "pages" / "unknown.html"),
        ],
    )
    assert {o.terminal for o in r.sources} == {"rejected_page"}
    assert session.scalar(select(func.count()).select_from(P.Product)) == 0


def test_conflicting_sources_route_to_review(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    other = mutate(tmp_path, "card_everyday_cash.html", "3% of each transaction", "2% of each transaction")
    a = source(reg, "everyday-cash")
    b = a.model_copy(
        update={
            "slug": "everyday-cash-offer",
            "fixture_path": str(other),
            "source_url": HttpUrl("https://www.examplebank.example/credit-cards/everyday-cash/offer"),
        }
    )
    reg.sources.append(b)
    r = run(session, settings, reg, [a, b])
    assert r.products[0].decision == "review"
    item = session.scalar(select(S.ManualReviewItem).where(S.ManualReviewItem.reason_code == "conflict"))
    assert item.context["conflicts"][0]["field"] == "foreign_tx_fee_pct"
    assert len(item.context["conflicts"][0]["values"]) == 2


def test_manual_capture_goes_through_same_pipeline(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.ingest.fetch import FetchResult
    from bankrec.ingest.pipeline import Pipeline

    reg = registry()
    src = source(reg, "secured")
    body = (FIX / "card_secured.html").read_bytes()
    when = datetime(2026, 10, 1, tzinfo=UTC)
    fr = FetchResult(
        str(src.source_url),
        str(src.source_url),
        200,
        "text/html",
        body,
        when,
        capture_method="manual",
        capture_conditions={
            "capture_context": "public_default",
            "login": False,
            "method": "manual",
            "captured_at_basis": "cli_argument",
        },
    )
    p = Pipeline(session, settings, reg, fetcher=None)
    r = p.run([], manual=[(src, fr)])
    session.commit()
    assert r.sources[0].terminal == "published" and r.sources[0].capture_method == "manual"
    snap = session.scalar(select(S.PageSnapshot))
    assert snap.capture_method == "manual" and snap.retrieved_at == when


def test_revalidation_outbox_is_transactional(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.ingest.fetch import FixtureFetcher
    from bankrec.ingest.pipeline import Pipeline
    from tests.integration.helpers import REPO

    reg = registry()
    Pipeline(session, settings, reg, fetcher=FixtureFetcher(settings, REPO)).run([source(reg, "secured")])
    session.rollback()
    assert session.scalar(select(func.count()).select_from(S.RevalidationOutbox)) == 0
    assert session.scalar(select(func.count()).select_from(P.Product)) == 0


def test_every_source_has_terminal_status_in_report(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.reports.writer import write_reports

    reg = registry()
    srcs = [source(reg, "secured"), source(reg, "everyday-cash", FIX / "pages" / "blocked.html")]
    r = run(session, settings, reg, srcs)
    d = write_reports(session, r, reg, Path(settings.reports_dir), datetime.now(UTC))
    status = (d / "source_status.csv").read_text()
    for s in srcs:
        assert s.source_id in status
    failures = (d / "retrieval_failures.csv").read_text().splitlines()
    assert failures[0] == "bank,url,time,stage,failure,detail,retry_status,next_action"
    assert "BOT_CHALLENGE" in failures[1] and "manual capture" in failures[1]
    mv = (d / "manual_verification_needed.md").read_text()
    assert "data/manual_snapshots/example_bank/everyday-cash.html" in mv
    for name in [
        "summary.md",
        "counts.csv",
        "duplicates.csv",
        "published_records.md",
        "stale_records.csv",
        "expired_offers.csv",
        "recheck_pending.csv",
        "cross_check_conflicts.csv",
        "recommendation_ready.csv",
        "page_classifications.csv",
        "parser_errors.csv",
        "missing_fields.csv",
        "conflicts.csv",
        "rejected_records.csv",
        "review_items.csv",
    ]:
        assert (d / name).exists(), name


def test_terminal_assertion_fails_loudly(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.ingest.pipeline import Pipeline

    reg = registry()

    class Drop:
        def fetch(self, src, bank):  # type: ignore[no-untyped-def]
            raise SystemExit  # never reached

    p = Pipeline(session, settings, reg, fetcher=Drop())
    p._process = lambda src, fr: None  # type: ignore[method-assign]
    p.fetcher = type("F", (), {"fetch": lambda self, s, b: None})()
    with pytest.raises(RuntimeError, match="without a terminal status"):
        p.run([source(reg, "secured")])


def test_stale_window_drops_label(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.freshness import product_label

    reg = registry()
    run(session, settings, reg, [source(reg, "high-yield")])
    p = _product(session, "Example Bank High Yield Savings")
    later = datetime.now(UTC) + timedelta(days=8)
    label, reasons = product_label(
        published=True,
        terms_confirmed_at=p.last_confirmed_at,
        apy_confirmed_at=p.apy_confirmed_at,
        product_type="savings",
        missing_key=[],
        recheck_pending=False,
        provider_only_fields=[],
        now=later,
    )
    assert label == "partially_verified" and "APY not recently verified" in reasons


def test_degraded_capture_keeps_prod_values_and_proposes_no_removal(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # DESIGN §24.18: a capture that lost a section the published capture had (here the earn list; the Amex static
    # shells lost the APR) is CAPTURE_DEGRADED: no candidate, no diff, no review item, prod unchanged.
    reg = registry()
    run(session, settings, reg)
    before = _product(session, "Example Bank Secured Card")
    fee, rates = before.card.annual_fee_cents, sorted((r.category, r.rate) for r in before.reward_rates)
    html = (FIX / "card_secured.html").read_text()
    s, e = (
        html.index('<ul class="earn-rates">'),
        html.index("</ul>", html.index('<ul class="earn-rates">')) + 5,
    )
    shell = tmp_path / "secured_shell.html"
    shell.write_text(html[:s] + html[e:])
    r = run(session, settings, reg, [source(reg, "secured", shell)])
    [o] = r.sources
    assert (o.terminal, o.failure) == ("retrieval_failed", Failure.CAPTURE_DEGRADED)
    assert "earn" in o.detail
    assert not r.products and not r.review_items
    session.expire_all()
    p = _product(session, "Example Bank Secured Card")
    assert not p.recheck_pending and p.card.annual_fee_cents == fee
    assert sorted((x.category, x.rate) for x in p.reward_rates) == rates
    snap = session.scalar(
        select(S.PageSnapshot)
        .where(S.PageSnapshot.source_id == o.source.source_id)
        .order_by(S.PageSnapshot.retrieved_at.desc())
    )
    assert snap.outcome == "CAPTURE_DEGRADED"
    # the next good capture goes through normally
    r2 = run(session, settings, reg, [source(reg, "secured")])
    assert r2.sources[0].terminal in {"published", "unchanged"}


def test_tiered_offer_is_published_with_its_tiers(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The prod offers table rejected amount_qualifier 'tiered' (the United approvals failed on the check constraint).
    reg = registry()
    tiered = mutate(
        tmp_path,
        "card_example_air_miles.html",
        "Bonus as high as 60,000 miles after you spend $3,000 within the first 90 days.",
        "Earn up to 60,000 bonus miles after qualifying activities. Earn 50,000 bonus miles after you spend $3,000 on "
        "purchases in the first 3 months. Plus, earn 10,000 bonus miles after you add an authorized user in the first "
        "3 months.",
    )
    run(session, settings, reg, [source(reg, "example-air-miles", tiered)])
    [o] = session.scalars(select(P.Offer)).all()
    assert (o.amount_qualifier, o.amount_max) == ("tiered", 60000)
    assert [
        (t["amount"], t["requirement_min_cents"], t["window_count"], t["window_unit"]) for t in o.tiers
    ] == [
        (50000, 300000, 3, "months"),
        (10000, None, None, None),
    ]
