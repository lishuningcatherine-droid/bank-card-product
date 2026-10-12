from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.review import service as R
from tests.integration.helpers import FIX, mutate, registry, run, source

pytestmark = pytest.mark.db
NOW = datetime.now(UTC)


def test_approve_major_change_publishes_version(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    f = mutate(tmp_path, "savings_high_yield.html", "4.00% APY", "4.60% APY")
    run(session, settings, reg, [source(reg, "high-yield", f)])
    item = session.scalar(select(S.ManualReviewItem).where(S.ManualReviewItem.reason_code == "major_change"))
    with pytest.raises(R.ReviewError, match="reviewer"):
        R.approve(session, reg, item.id, reviewer="", note="x", now=NOW)
    session.rollback()
    item = session.scalar(select(S.ManualReviewItem).where(S.ManualReviewItem.reason_code == "major_change"))
    assert (
        R.approve(session, reg, item.id, reviewer="alice", note="confirmed on page", now=NOW) == "published"
    )
    session.commit()
    p = session.scalar(select(P.Product).where(P.Product.official_name == "Example Bank High Yield Savings"))
    assert str(p.savings.apy_pct) == "4.6000" and not p.recheck_pending and p.current_version == 2
    d = session.scalar(select(S.ReviewDecision))
    assert (d.reviewer, d.action, d.note) == ("alice", "approve", "confirmed on page")


def test_needs_review_record_publishes_only_after_approval(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(
        session,
        settings,
        reg,
        [
            source(reg, "everyday-cash", FIX / "pages" / "comparison.html").model_copy(
                update={"expected_entity": "Example Bank Everyday Cash Card"}
            )
        ],
    )
    assert session.scalar(select(func.count()).select_from(P.Product)) == 0


def test_edit_requires_evidence_in_snapshot(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg, [source(reg, "high-yield", FIX / "pages" / "savings_static_nan.html")])
    item = session.scalar(select(S.ManualReviewItem))
    with pytest.raises(R.ReviewError, match="evidence"):
        R.edit(session, item.id, field="apy_pct", value="4.00", evidence="4.00% APY", reviewer="bob", now=NOW)
    R.edit(
        session,
        item.id,
        field="monthly_fee_cents",
        value=0,
        evidence="Monthly fee $0",
        reviewer="bob",
        now=NOW,
    )
    session.commit()
    assert session.get(S.ManualReviewItem, item.id).state == "edited"
    assert session.scalar(select(S.ReviewDecision)).action == "edit"


def test_reject_and_merge(session, settings) -> None:  # type: ignore[no-untyped-def]
    reg = registry()
    run(session, settings, reg)
    keys = [
        p.canonical_key for p in session.scalars(select(P.Product).where(P.Product.product_type == "savings"))
    ]
    R.merge_products(session, keys[0], keys[1], reviewer="carol", note="same product", now=NOW)
    session.commit()
    b = session.scalar(select(P.Product).where(P.Product.canonical_key == keys[1]))
    a = session.scalar(select(P.Product).where(P.Product.canonical_key == keys[0]))
    assert b.status == "withdrawn" and b.official_name in {x.alias for x in a.aliases}
    assert session.scalar(select(S.ReviewDecision)).action == "merge"
    assert session.get(P.Product, b.id) is not None  # never deleted


def _tccp(rows: list[dict[str, str]], path: Path) -> Path:
    import csv

    from bankrec.crosscheck.cfpb import tccp_mapping

    cols = list(tccp_mapping()["columns"].values())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def test_cfpb_crosscheck_conflict_explained_and_never_published(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from bankrec.crosscheck.cfpb import RegulatorSchemaError, parse_tccp_csv, run_crosscheck

    reg = registry()
    run(session, settings, reg)
    before = session.scalar(select(func.count()).select_from(P.Product))
    f = _tccp(
        [
            {
                "Institution Name": "EXAMPLE BANK, N.A.",
                "Product Name": "Example Bank Everyday Cash Card",
                "Purchase APR Min": "19.24",
                "Purchase APR Max": "28.24",
                "Annual Fee": "0",
                "Foreign Transaction Fee": "3",
            },
            {
                "Institution Name": "EXAMPLE BANK, N.A.",
                "Product Name": "Example Bank Secured Card",
                "Purchase APR Min": "29.99",
                "Purchase APR Max": "29.99",
                "Annual Fee": "25",
            },
            {
                "Institution Name": "EXAMPLE BANK, N.A.",
                "Product Name": "Example Bank Platinum Card",
                "Annual Fee": "0",
            },
            {"Institution Name": "SOME OTHER ISSUER", "Product Name": "Other Card", "Annual Fee": "0"},
        ],
        tmp_path / "tccp_synthetic.csv",
    )
    data = f.read_bytes()
    summ = run_crosscheck(
        session,
        reg,
        dataset="cfpb_tccp",
        release_id="synthetic-1",
        as_of=date.today(),
        file_url="file://synthetic",
        data=data,
        rows=parse_tccp_csv(data),
        run_id="cc1",
        now=NOW,
    )
    session.commit()
    assert summ.matched == 2 and summ.conflicts == 1 and summ.unmatched == 2 and summ.agreements >= 4
    conflict = session.scalar(
        select(S.ManualReviewItem).where(S.ManualReviewItem.item_kind == "regulator_conflict")
    )
    assert conflict.context["field"] == "annual_fee_cents" and conflict.context["regulator"] == 2500
    secured = session.scalar(select(P.Product).where(P.Product.official_name == "Example Bank Secured Card"))
    assert secured.card.annual_fee_cents == 0 and not secured.recheck_pending  # no downgrade (Q3)
    assert session.scalar(select(func.count()).select_from(P.Product)) == before  # never creates products
    assert (
        session.scalar(select(func.count()).select_from(P.Offer).where(P.Offer.offer_url.like("file://%")))
        == 0
    )
    with pytest.raises(RegulatorSchemaError):
        parse_tccp_csv(b"Wrong,Columns\n1,2\n")


def test_cfpb_difference_explained_by_history(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from bankrec.crosscheck.cfpb import parse_tccp_csv, run_crosscheck

    reg = registry()
    run(session, settings, reg, [source(reg, "high-yield"), source(reg, "everyday-cash")])
    p = session.scalar(select(P.Product).where(P.Product.official_name == "Example Bank Everyday Cash Card"))
    v1 = session.scalar(select(P.ProductVersion).where(P.ProductVersion.product_id == p.id))
    v1.valid_from = NOW - timedelta(days=200)
    v1.valid_to = NOW - timedelta(days=10)
    v1.snapshot = {**v1.snapshot, "fields": {**v1.snapshot["fields"], "foreign_tx_fee_pct": "2"}}
    session.commit()
    f = _tccp(
        [
            {
                "Institution Name": "EXAMPLE BANK, N.A.",
                "Product Name": "Example Bank Everyday Cash Card",
                "Foreign Transaction Fee": "2",
            }
        ],
        tmp_path / "t.csv",
    )
    summ = run_crosscheck(
        session,
        reg,
        dataset="cfpb_tccp",
        release_id="old",
        as_of=(NOW - timedelta(days=100)).date(),
        file_url="x",
        data=f.read_bytes(),
        rows=parse_tccp_csv(f.read_bytes()),
        run_id="cc2",
        now=NOW,
    )
    assert summ.explained == 1 and summ.conflicts == 0


def test_provider_gate_and_labels(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from bankrec.ingest.providers.apply import apply_records
    from bankrec.ingest.providers.base import (
        ProviderConfig,
        ProviderGateError,
        ProviderLicense,
        ProviderRecord,
        check_gate,
        load_providers,
    )

    assert load_providers() == []  # nothing enabled; the fake is test_only
    assert [p.provider_id for p in load_providers(include_test_only=True)] == ["example_provider"]
    bad = ProviderConfig(
        provider_id="x", display_name="X", enabled=True, license=ProviderLicense(status="unconfirmed")
    )
    with pytest.raises(ProviderGateError):
        check_gate(bad)
    with pytest.raises(ProviderGateError):
        check_gate(bad.model_copy(update={"license": ProviderLicense(status="confirmed")}))
    reg = registry()
    run(session, settings, reg, [source(reg, "voyager-rewards")])
    ok = ProviderConfig(
        provider_id="example_provider",
        display_name="Fake",
        enabled=True,
        test_only=True,
        license=ProviderLicense(
            status="confirmed",
            confirmed_by="owner",
            confirmed_on=date(2026, 1, 1),
            display_permitted=True,
            attribution_text="Fake Data (licensed)",
        ),
    )
    rec = ProviderRecord(
        external_id="1",
        bank_id="example_bank",
        product_name="Example Bank Voyager Rewards Card",
        product_type="credit_card",
        as_of=NOW,
        fields={"cash_apr_pct": "29.99", "annual_fee_cents": 1000},
    )
    stats = apply_records(session, ok, [rec], NOW)
    session.commit()
    p = session.scalar(
        select(P.Product).where(P.Product.official_name == "Example Bank Voyager Rewards Card")
    )
    assert stats == {"filled": 1, "conflicts": 1, "skipped": 0}
    assert p.provider_only_fields == ["cash_apr_pct"] and p.card.annual_fee_cents == 9500  # official wins


def test_seed_export_roundtrip_refuses_test_data(session, settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from bankrec.db.seed import export_prod, seed_prod

    reg = registry()
    run(session, settings, reg, [source(reg, "secured")])
    out = tmp_path / "prod.jsonl"
    assert export_prod(session, out) > 5
    for t in [
        "field_provenance",
        "offer_versions",
        "product_versions",
        "offers",
        "product_benefits",
        "product_reward_rates",
        "savings_account_details",
        "checking_account_details",
        "credit_card_details",
        "product_aliases",
        "products",
        "reward_categories",
        "banks",
    ]:
        session.execute(P.ProdBase.metadata.tables[f"prod.{t}"].delete())
    session.commit()
    with pytest.raises(ValueError, match="test_only"):
        seed_prod(session, out)
    stats = seed_prod(session, out, include_test=True)
    session.commit()
    assert stats["products"] == 1 and session.scalar(select(func.count()).select_from(P.Product)) == 1


def test_revalidation_dispatch_signed(session, settings) -> None:  # type: ignore[no-untyped-def]
    import hashlib
    import hmac
    import json

    from bankrec.revalidate import dispatch

    reg = registry()
    run(session, settings, reg, [source(reg, "secured")])
    assert dispatch(session, settings, NOW)["pending"] > 0  # not configured → stays pending
    st = settings.model_copy(
        update={
            "revalidate_url": "https://web.internal/api/internal/revalidate",
            "revalidate_secret": "x" * 32,
        }
    )
    got: list[httpx.Request] = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (got.append(r), httpx.Response(200))[1]))
    stats = dispatch(session, st, NOW, client)
    assert stats["sent"] >= 1 and stats["failed"] == 0
    sig = dict(kv.split("=") for kv in got[0].headers["X-Bankrec-Signature"].split(","))
    mac = hmac.new(b"x" * 32, f"{sig['t']}.".encode() + got[0].content, hashlib.sha256).hexdigest()
    assert mac == sig["v1"] and "listing:credit_card" in json.loads(got[0].content)["tags"]


def test_schedule_lock_and_crontab(engine) -> None:  # type: ignore[no-untyped-def]
    from bankrec.schedule import crontab, try_lock, unlock

    tab = crontab()
    assert "0 */12 * * * bankrec ingest --tier apy" in tab and "--tier offer" in tab and "--tier terms" in tab
    assert "--tier regulator_release" in tab
    c1, c2 = engine.connect(), engine.connect()
    try:
        assert try_lock(c1, "apy") and not try_lock(c2, "apy") and try_lock(c2, "offer")
        unlock(c1, "apy")
        assert try_lock(c2, "apy")
    finally:
        c1.close()
        c2.close()
