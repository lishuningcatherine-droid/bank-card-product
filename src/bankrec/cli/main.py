"""``bankrec`` command line: ingestion, review, reports, database, scheduling."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from bankrec.db.session import get_engine
from bankrec.registry.loader import EmptyRegistryError, RegistryError, load_registry
from bankrec.settings import REPO_ROOT, get_settings

app = typer.Typer(
    no_args_is_help=True, help="Bank product recommendation platform — pipeline and review tools."
)
review_app = typer.Typer(no_args_is_help=True, help="Review uncertain records (CLI-only workflow).")
report_app = typer.Typer(no_args_is_help=True, help="Reports.")
db_app = typer.Typer(no_args_is_help=True, help="Database management.")
schedule_app = typer.Typer(no_args_is_help=True, help="Scheduling helpers.")
revalidate_app = typer.Typer(no_args_is_help=True, help="Next.js on-demand revalidation.")
registry_app = typer.Typer(no_args_is_help=True, help="Source registry.")
crosscheck_app = typer.Typer(no_args_is_help=True, help="Regulator cross-checks (CFPB).")
api_app = typer.Typer(no_args_is_help=True, help="API utilities.")
ml_app = typer.Typer(no_args_is_help=True, help="Ranking-model training interface (DESIGN §26.8).")
events_app = typer.Typer(no_args_is_help=True, help="Consented anonymous ranking events (DESIGN §26.7).")
offers_app = typer.Typer(
    no_args_is_help=True, help="Offer tracker: campaigns, history, manual entries (DESIGN §27)."
)
for name, sub in [
    ("review", review_app),
    ("report", report_app),
    ("db", db_app),
    ("schedule", schedule_app),
    ("revalidate", revalidate_app),
    ("registry", registry_app),
    ("crosscheck", crosscheck_app),
    ("api", api_app),
    ("events", events_app),
    ("ml", ml_app),
    ("offers", offers_app),
]:
    app.add_typer(sub, name=name)


def _session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def _now() -> datetime:
    return datetime.now(UTC)


def _registry(include_test: bool, require: bool = True) -> Any:
    from bankrec.ingest.adapters import known_parsers

    return load_registry(
        include_test_only=include_test, known_parsers=known_parsers(), require_sources=require
    )


def _reviewer(reviewer: str | None) -> str:
    r = reviewer or get_settings().reviewer
    if not r:
        typer.echo("error: a reviewer name is required (--reviewer or BANKREC_REVIEWER)", err=True)
        raise typer.Exit(2)
    return r


# --------------------------------------------------------------------------------------------- registry
@registry_app.command("validate")
def registry_validate(include_test: bool = typer.Option(False, "--include-test")) -> None:
    """Validate config/banks and config/sources. Exit 1 on any error."""
    try:
        reg = _registry(include_test, require=False)
    except RegistryError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo(
        json.dumps(
            {
                "banks": sorted(reg.banks),
                "enabled_sources": len(reg.enabled()),
                "banks_without_sources": reg.banks_without_sources,
            },
            indent=1,
        )
    )


# --------------------------------------------------------------------------------------------- ingest
@app.command()
def ingest(
    tier: Annotated[str | None, typer.Option(help="apy | offer | terms | regulator_release")] = None,
    bank: Annotated[str | None, typer.Option(help="limit to one bank")] = None,
    source: Annotated[list[str] | None, typer.Option(help="limit to source ids (bank:slug)")] = None,
    manual: Annotated[Path | None, typer.Option(help="manually captured snapshot (HTML or PDF)")] = None,
    source_url: Annotated[str | None, typer.Option(help="official URL of the manual snapshot")] = None,
    captured_at: Annotated[str | None, typer.Option(help="capture date YYYY-MM-DD for --manual")] = None,
    include_test: Annotated[bool, typer.Option("--include-test", help="include test_only banks")] = False,
    allow_empty: Annotated[bool, typer.Option("--allow-empty", help="CI smoke runs only")] = False,
    render: Annotated[bool, typer.Option(help="use Playwright for requires_render sources")] = True,
    trigger: Annotated[str, typer.Option(help="manual | cron | github")] = "manual",
    reprocess: Annotated[
        bool, typer.Option("--reprocess", help="re-apply extraction and change policy to unchanged pages")
    ] = False,
) -> None:
    """Run the pipeline for enabled sources (optionally one tier/bank) and write reports."""
    from bankrec.ingest.fetch import Fetcher, FixtureFetcher
    from bankrec.ingest.pipeline import Pipeline
    from bankrec.logging_setup import configure
    from bankrec.reports.writer import write_reports
    from bankrec.schedule import LockLost, TierLock

    configure()
    settings = get_settings()
    if (
        trigger in {"cron", "github"}
        and settings.scheduler != {"cron": "worker", "github": "github"}[trigger]
    ):
        typer.echo(f"skipped: BANKREC_SCHEDULER={settings.scheduler} does not select the {trigger} scheduler")
        raise typer.Exit(0)
    if include_test and settings.env == "prod":
        typer.echo("error: test_only banks are refused in production", err=True)
        raise typer.Exit(2)
    try:
        reg = _registry(include_test, require=not (allow_empty or manual))
    except EmptyRegistryError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(3) from e
    except RegistryError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    sources = reg.enabled(tier=tier, bank=bank)
    if source:
        sources = [s for s in sources if s.source_id in set(source)]
    manual_items: list[Any] = []
    if manual:
        manual_items.append(_manual_item(reg, manual, source_url, captured_at))
        sources = []
    engine = get_engine()
    lock = TierLock(engine, tier or "all")
    if not lock.acquire():
        typer.echo(f"skipped: tier {lock.tier} already running")
        raise typer.Exit(0)
    fetcher: Any = Fetcher(settings)
    fixture = FixtureFetcher(settings, REPO_ROOT)
    browser_ctx = None
    renderer = None
    try:
        if render and any(s.requires_render and not s.fixture_path for s in sources):
            from playwright.sync_api import sync_playwright

            from bankrec.ingest.render import Renderer

            browser_ctx = sync_playwright().start()
            browser = browser_ctx.chromium.launch(headless=True, executable_path=settings.chromium_executable)
            renderer = Renderer(settings, browser, fetcher.robots, fetcher.limiter)

        class Router:
            def fetch(self, src: Any, bnk: Any) -> Any:
                return (fixture if src.fixture_path else fetcher).fetch(src, bnk)

            def close(self) -> None:
                fetcher.close()

        with sessionmaker(bind=engine, expire_on_commit=False)() as s:
            p = Pipeline(
                s,
                settings,
                reg,
                fetcher=Router(),
                renderer=renderer,
                trigger=trigger,
                tier=tier,
                repo_root=REPO_ROOT,
                reprocess=reprocess,
            )
            result = p.run(sources, manual=manual_items)
            lock.ensure()  # never commit without the lock: a lost lock rolls this run's work back
            s.commit()
            out = write_reports(s, result, reg, settings.reports_dir, _now())
            lock.ensure()
            s.commit()
            from bankrec.revalidate import dispatch

            dispatch(s, settings, _now())
            lock.ensure()
            s.commit()
        typer.echo(json.dumps({"run_id": result.run_id, "reports": str(out), **p.counts()}, indent=1))
        if reg.banks_without_sources and not include_test and not manual:
            typer.echo(
                f"warning: banks without enabled sources: {', '.join(reg.banks_without_sources)}", err=True
            )
    except LockLost as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(4) from e
    finally:
        fetcher.close()
        if browser_ctx is not None:
            browser_ctx.stop()
        lock.release()


def _manual_item(reg: Any, path: Path, source_url: str | None, captured_at: str | None) -> Any:
    from bankrec.ingest.fetch import FetchResult
    from bankrec.registry.urls import canonicalize

    if not source_url:
        typer.echo("error: --source-url is required with --manual", err=True)
        raise typer.Exit(2)
    if not path.exists():
        typer.echo(f"error: {path} not found", err=True)
        raise typer.Exit(2)
    match = [s for s in reg.sources if canonicalize(str(s.source_url)) == canonicalize(source_url)]
    if not match:
        typer.echo("error: --source-url is not in the registry; add it (enabled or disabled) first", err=True)
        raise typer.Exit(2)
    src = match[0]
    bank = reg.bank(src.bank_id)
    if captured_at:
        when = datetime.combine(date.fromisoformat(captured_at), datetime.min.time(), UTC)
        basis = "cli_argument"
    else:
        when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        basis = "file_mtime"
    body = path.read_bytes()
    ctype = "application/pdf" if body[:5] == b"%PDF-" else "text/html; charset=utf-8"
    url = canonicalize(source_url, bank.meaningful_query_params)
    return src, FetchResult(
        url,
        url,
        200,
        ctype,
        body,
        when,
        capture_method="manual",
        capture_conditions={
            "capture_context": "public_default",
            "method": "manual",
            "login": False,
            "url_canonical": url,
            "url_final": url,
            "captured_at": when.isoformat(),
            "captured_at_basis": basis,
            "file": str(path),
        },
    )


@app.command()
def survey(include_cfpb: bool = True) -> None:
    """Reachability survey: robots.txt and official sitemaps per bank (never retried in a loop)."""
    from dataclasses import asdict

    from bankrec.ingest.discovery import survey_bank
    from bankrec.ingest.fetch import Fetcher

    settings = get_settings()
    reg = _registry(False, require=False)
    f = Fetcher(settings, max_attempts=1)
    rows = []
    try:
        for b in reg.banks.values():
            if b.role == "regulator" and not include_cfpb:
                continue
            rows += [asdict(r) for r in survey_bank(f, b)]
    finally:
        f.close()
    d = settings.reports_dir / "survey"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    typer.echo(json.dumps(rows, indent=1))
    typer.echo(f"written {out}")


@app.command()
def discover(bank: str) -> None:
    """Write config/sources/<bank>.discovered.yaml from official sitemaps (never auto-enabled)."""
    from bankrec.ingest.discovery import discover as run_discover
    from bankrec.ingest.fetch import Fetcher
    from bankrec.settings import CONFIG_DIR

    reg = _registry(False, require=False)
    f = Fetcher(get_settings(), max_attempts=1)
    try:
        typer.echo(str(run_discover(f, reg, bank, CONFIG_DIR)))
    finally:
        f.close()


# --------------------------------------------------------------------------------------------- review
@review_app.command("list")
def review_list(
    type: Annotated[str | None, typer.Option("--type")] = None,
    bank: Annotated[str | None, typer.Option()] = None,
) -> None:
    from bankrec.review.service import list_items

    with _session() as s:
        for it in list_items(s, product_type=type, bank=bank):
            typer.echo(
                f"{it.id:>5}  {it.item_kind:<18} {it.reason_code:<22} {it.bank_id or '-':<18} "
                f"{it.canonical_key or ''}"
            )


@review_app.command("show")
def review_show(item_id: int) -> None:
    from bankrec.review.service import show

    with _session() as s:
        typer.echo(json.dumps(show(s, item_id), indent=1, default=str))


@review_app.command("approve")
def review_approve(
    item_id: int,
    note: Annotated[str, typer.Option(help="why this is correct")],
    reviewer: Annotated[str | None, typer.Option()] = None,
    include_test: bool = typer.Option(False, "--include-test"),
) -> None:
    from bankrec.review.service import approve

    r = _reviewer(reviewer)
    with _session() as s:
        res = approve(s, _registry(include_test, require=False), item_id, reviewer=r, note=note, now=_now())
        s.commit()
    typer.echo(res)


@review_app.command("auto-approve")
def review_auto_approve(
    dry_run: bool = typer.Option(False, "--dry-run", help="list what would be approved"),
    log: Annotated[Path, typer.Option(help="spot-check log to regenerate")] = Path("docs/AUTO_APPROVED.md"),
) -> None:
    """Approve pure, page-evidenced additions that pass every check; everything else waits for the owner."""
    from bankrec.review import auto

    with _session() as s:
        rows = auto.run(s, _registry(False, require=False), _now(), dry_run=dry_run)
        if not dry_run:
            s.commit()
            auto.write_log(s, log, _now())
    for r in rows:
        typer.echo(
            f"{'would approve' if dry_run else 'approved'} {r['id']}  {r['product']}  {r['content']}  {r['source']}"
        )
    typer.echo(f"{len(rows)} item(s)")


@review_app.command("reject")
def review_reject(
    item_id: int,
    reason: Annotated[str, typer.Option()],
    reviewer: Annotated[str | None, typer.Option()] = None,
) -> None:
    from bankrec.review.service import reject

    r = _reviewer(reviewer)
    with _session() as s:
        reject(s, item_id, reviewer=r, reason=reason, now=_now())
        s.commit()
    typer.echo("rejected")


@review_app.command("merge")
def review_merge(
    a: str,
    b: str,
    note: Annotated[str | None, typer.Option()] = None,
    reviewer: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Merge canonical product B into A (B becomes an alias; B is withdrawn, never deleted)."""
    from bankrec.review.service import merge_products

    r = _reviewer(reviewer)
    with _session() as s:
        merge_products(s, a, b, reviewer=r, note=note, now=_now())
        s.commit()
    typer.echo("merged")


@review_app.command("edit")
def review_edit(
    item_id: int,
    field: Annotated[str, typer.Option()],
    value: Annotated[str, typer.Option()],
    evidence: Annotated[str, typer.Option(help="quoted text that exists in a stored snapshot")],
    reviewer: Annotated[str | None, typer.Option()] = None,
) -> None:
    from bankrec.review.service import ReviewError, edit

    r = _reviewer(reviewer)
    parsed: Any = value
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads(value)
    with _session() as s:
        try:
            edit(s, item_id, field=field, value=parsed, evidence=evidence, reviewer=r, now=_now())
        except ReviewError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from e
        s.commit()
    typer.echo("edited (approve the item to publish)")


# --------------------------------------------------------------------------------------------- reports
@report_app.command("stale")
def report_stale() -> None:
    """List everything due for recheck (stale products, APYs and offers)."""
    from bankrec.db import prod as P
    from bankrec.freshness import is_stale, offer_state

    now = _now()
    with _session() as s:
        for p in s.scalars(select(P.Product).where(P.Product.status == "published")):
            if is_stale(p.last_confirmed_at, "terms", now):
                typer.echo(
                    f"terms  {p.bank_id:<18} {p.official_name}  confirmed {p.last_confirmed_at:%Y-%m-%d}"
                )
            if p.product_type == "savings" and is_stale(p.apy_confirmed_at, "apy", now):
                typer.echo(f"apy    {p.bank_id:<18} {p.official_name}")
            for o in p.offers:
                st = offer_state(o.status, o.expiration_date, o.last_confirmed_at, now)
                if st in {"stale", "expired"}:
                    typer.echo(f"offer  {p.bank_id:<18} {p.official_name}  {o.offer_type} {st}")


# --------------------------------------------------------------------------------------------- db
@db_app.command("upgrade")
def db_upgrade() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    typer.echo("migrated")


@db_app.command("check-target")
def db_check_target() -> None:
    """Describe the database DATABASE_URL points to, without printing the URL or any credential: server version,
    direct or pooled endpoint, migration revision, extensions and row counts of the main tables. Read-only."""
    from sqlalchemy import text

    from bankrec.schedule import is_pooled

    engine = get_engine()
    host = engine.url.host or ""
    with engine.connect() as c:
        out: dict[str, Any] = {
            "server_version": c.execute(text("SHOW server_version")).scalar(),
            "endpoint": "pooled (transaction-level locks)"
            if is_pooled(engine)
            else "direct (session-level locks)",
            # Neon sets one; the scheduled run holds its lock on an autocommit connection, so it is never idle in a
            # transaction (DESIGN §21.1)
            "idle_in_transaction_session_timeout": c.execute(
                text("SHOW idle_in_transaction_session_timeout")
            ).scalar(),
            "host_kind": "neon"
            if host.endswith(".neon.tech")
            else "local"
            if host in ("localhost", "127.0.0.1", "db")
            else "other",
            "alembic_revision": c.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
            if c.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
            else None,
            "extensions": sorted(r[0] for r in c.execute(text("SELECT extname FROM pg_extension"))),
            "rows": {},
        }
        for t in ("prod.products", "prod.offers", "prod.tracked_cards", "prod.campaigns", "prod.campaign_versions",
                  "prod.application_rules", "staging.manual_campaign_entries", "staging.page_snapshots"):  # fmt: skip
            if c.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar():
                out["rows"][t] = c.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # fixed table names
    typer.echo(json.dumps(out, indent=1, default=str))


@db_app.command("relabel")
def db_relabel() -> None:
    """Recompute each published product's key-field gaps under the current config/validation.yaml.

    Only ``critical_missing`` changes (it is ``missing_fields`` ∩ the policy's key fields); no value is touched.
    Use after a policy change such as moving a field from ``key`` to ``conditional``."""
    from sqlalchemy import select

    from bankrec.db import prod as P
    from bankrec.publish.publisher import enqueue_revalidation, product_tags
    from bankrec.validation.rules import policy

    key = policy()["key"]
    changed = 0
    with _session() as s:
        for p in s.scalars(select(P.Product)):
            new = [f for f in key[p.product_type] if f in (p.missing_fields or [])]
            if new != list(p.critical_missing or []):
                p.critical_missing = new
                enqueue_revalidation(s, product_tags(p), _now())
                changed += 1
        s.commit()
    typer.echo(json.dumps({"relabelled": changed}))


@db_app.command("export-prod")
def db_export(path: Path) -> None:
    from bankrec.db.seed import export_prod

    with _session() as s:
        typer.echo(f"{export_prod(s, path)} rows written to {path}")


@db_app.command("seed")
def db_seed(path: Path, include_test: bool = typer.Option(False, "--include-test")) -> None:
    """Load published prod data from an export. Refuses test_only data unless --include-test (never in prod)."""
    from bankrec.db.seed import seed_prod

    if include_test and get_settings().env == "prod":
        typer.echo("error: --include-test is refused in production", err=True)
        raise typer.Exit(2)
    with _session() as s:
        try:
            stats = seed_prod(s, path, include_test=include_test)
        except ValueError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from e
        s.commit()
    typer.echo(json.dumps(stats, indent=1))


# --------------------------------------------------------------------------------------------- schedule/revalidate
@schedule_app.command("crontab")
def schedule_crontab() -> None:
    from bankrec.schedule import crontab

    typer.echo(crontab(), nl=False)


@revalidate_app.command("dispatch")
def revalidate_dispatch() -> None:
    from bankrec.revalidate import dispatch

    with _session() as s:
        stats = dispatch(s, get_settings(), _now())
        s.commit()
    typer.echo(json.dumps(stats))


# --------------------------------------------------------------------------------------------- crosscheck
@crosscheck_app.command("tccp")
def crosscheck_tccp(
    path: Path,
    release_id: Annotated[str, typer.Option()],
    as_of: Annotated[str | None, typer.Option()] = None,
    file_url: Annotated[str, typer.Option()] = "",
    include_test: bool = typer.Option(False, "--include-test"),
) -> None:
    """Cross-check a downloaded TCCP release file against published values (never publishes)."""
    from bankrec.crosscheck.cfpb import RegulatorSchemaError, parse_tccp, run_crosscheck

    data = path.read_bytes()
    try:
        rows = parse_tccp(data)
    except RegulatorSchemaError as e:
        typer.echo(f"SCHEMA_DRIFT: {e}", err=True)
        raise typer.Exit(1) from e
    with _session() as s:
        summ = run_crosscheck(
            s,
            _registry(include_test, require=False),
            dataset="cfpb_tccp",
            release_id=release_id,
            as_of=date.fromisoformat(as_of) if as_of else None,
            file_url=file_url or str(path),
            data=data,
            rows=rows,
            run_id=f"crosscheck-{release_id}",
            now=_now(),
        )
        s.commit()
    typer.echo(json.dumps(summ.__dict__, default=str))


@api_app.command("openapi")
def api_openapi(path: Path = Path("docs/openapi.json")) -> None:
    """Write the published OpenAPI spec (the web app generates its TypeScript types from it)."""
    from bankrec.api.app import create_app

    spec = create_app().openapi()
    path.write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(f"wrote {path}")


@api_app.command("serve")
def api_serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    from bankrec.logging_setup import configure

    configure()
    uvicorn.run("bankrec.api.app:app", host=host, port=port, access_log=False, server_header=False)


def main() -> None:  # pragma: no cover
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    app(sys.argv[1:])


# --------------------------------------------------------------------------------------------- events
@events_app.command("purge")
def events_purge(
    days: Annotated[int | None, typer.Option(help="retention in days (default EVENT_RETENTION_DAYS)")] = None,
) -> None:
    """Delete events older than the retention period (run daily by the scheduler or cron)."""
    from bankrec import events as ev

    keep = days if days is not None else get_settings().event_retention_days
    with _session() as s:
        n = ev.purge(s, _now(), keep)
        s.commit()
    typer.echo(f"purged {n} event(s) older than {keep} days")


@events_app.command("delete")
def events_delete(anon_id: str) -> None:
    """Delete every event of one anonymous id (a visitor's request made outside the site)."""
    import uuid

    from bankrec import events as ev

    with _session() as s:
        n = ev.delete_for(s, uuid.UUID(anon_id))
        s.commit()
    typer.echo(f"deleted {n} event(s)")


# --------------------------------------------------------------------------------------------- ml
@ml_app.command("train")
def ml_train(
    type: Annotated[str, typer.Option("--type", help="credit_card | checking | savings")],
    out: Annotated[Path, typer.Option(help="artifact path, e.g. models/cards-v1.json")],
    model_id: Annotated[str | None, typer.Option("--id")] = None,
) -> None:
    """Train on recorded consented events and write an artifact with held-out metrics. It does NOT activate it."""
    from bankrec.rank import train as T
    from bankrec.rank.rankers import gate_failures, policy

    now = _now()
    with _session() as s:
        rows = T.build_dataset(s, type, now, allow_test_only=get_settings().allow_test_only)
    if not rows:
        typer.echo("no consented events for this product type yet; nothing to train on")
        raise typer.Exit(1)
    art = T.train(
        rows,
        product_type=type,
        data_source="events",
        now=now,
        model_id=model_id or f"{type}-{now:%Y%m%d%H%M}",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(art, indent=1) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}: {art['training']['n_lists']} views, metrics {art['metrics']}")
    for reason in gate_failures(art, policy()):
        typer.echo(f"  not deployable yet: {reason}")


@ml_app.command("check")
def ml_check(artifact: Path) -> None:
    """List the gates an artifact fails (config/ranking.yaml); exit 1 if any."""
    from bankrec.rank.rankers import gate_failures, load_artifact, policy

    bad = gate_failures(load_artifact(artifact), policy())
    for reason in bad:
        typer.echo(f"fails: {reason}")
    typer.echo("all gates pass" if not bad else f"{len(bad)} gate(s) fail")
    raise typer.Exit(1 if bad else 0)


@ml_app.command("approve")
def ml_approve(artifact: Path, by: Annotated[str, typer.Option(help="the owner's name")]) -> None:
    """Record the owner's approval in the artifact. Activation still needs config/ranking.yaml `active` and every
    other gate."""
    art = json.loads(artifact.read_text(encoding="utf-8"))
    art["approved_by"] = by
    art["approved_at"] = _now().isoformat()
    artifact.write_text(json.dumps(art, indent=1) + "\n", encoding="utf-8")
    typer.echo(f"approved by {by}; activate it by setting `active: {artifact}` in config/ranking.yaml")


# ---------------------------------------------------------------------------------------------- offer tracker (§27)


@offers_app.command("sync")
def offers_sync() -> None:
    """Update campaigns, versions, checks and statuses from the published offers (no fetching)."""
    from bankrec.tracker.sync import sync

    with _session() as s:
        rep = sync(s, _now())
        s.commit()
    typer.echo(json.dumps(rep.as_dict(), indent=1, default=str))


@offers_app.command("update")
def offers_update(
    render: Annotated[bool, typer.Option(help="use Playwright for requires_render sources")] = True,
    trigger: Annotated[str, typer.Option(help="manual | cron | github")] = "manual",
) -> None:
    """Fetch the tracked cards' official pages (robots.txt and rate limits apply), then sync campaigns."""
    from bankrec.tracker import config as tcfg

    ids = sorted({sid for c in tcfg.cards() for sid in c.get("source_ids", [])})
    with contextlib.suppress(typer.Exit):
        ingest(source=ids, render=render, trigger=trigger)
    offers_sync()


@offers_app.command("match")
def offers_match(
    path: Annotated[Path, typer.Argument(help="JSON file: {profile: {...}, campaign_ids?: [...]}")],
    brief: Annotated[bool, typer.Option(help="one block per offer instead of the full JSON")] = True,
) -> None:
    """Run the personal offer check (the same as POST /api/v1/campaigns/match) for a saved profile."""
    from bankrec.api.repository import Repository
    from bankrec.tracker import match
    from bankrec.tracker.profile import MatchRequest

    req = MatchRequest.model_validate_json(path.read_text(encoding="utf-8"))
    t = _now()
    with _session() as s:
        repo = Repository(s, allow_test_only=get_settings().allow_test_only)
        products = {str(p.id): p for p in repo.all_of_type("credit_card", t)}
        res = match.run(s, req, t, allow_demo=get_settings().allow_test_only, products=products)
    if not brief:
        typer.echo(res.model_dump_json(indent=1))
        return
    for a in res.items:
        typer.echo(f"\n== {a.bank_name} {a.card_name}: {a.action_label}")
        for r in a.action_reasons:
            typer.echo(f"   - {r}")
        for c in a.conflicts:
            typer.echo(f"   ! conflict [{c.basis}] {c.name}")
        typer.echo(f"   approval: {a.approval.label} | bonus: {a.bonus.label}")
        typer.echo(
            f"   reach: {a.reach.label} | appeal: {a.offer_appeal.label} | fit: {a.personal_fit.label}"
        )
        typer.echo(f"   first year: {a.first_year.text}")
    if res.questions:
        typer.echo("\nnext questions: " + " | ".join(q.text for q in res.questions))


@offers_app.command("add")
def offers_add(
    path: Annotated[
        Path, typer.Argument(help="YAML or JSON file with one entry (see docs/MANUAL_OFFERS.md)")
    ],
    by: Annotated[str, typer.Option(help="who is entering it")],
) -> None:
    """Enter a campaign by hand. It stays pending review until someone else approves it."""
    import yaml

    from bankrec.tracker.manual import ManualCampaignIn, add

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = ManualCampaignIn.model_validate(data)
    with _session() as s:
        row = add(s, entry, by=by, now=_now())
        s.commit()
        typer.echo(f"entry {row.id}: pending review")


@offers_app.command("amend")
def offers_amend(
    entry_id: int,
    path: Annotated[Path, typer.Argument(help="YAML or JSON file with the corrected entry")],
    by: Annotated[str, typer.Option(help="who amends it")],
    reason: Annotated[str, typer.Option(help="why (kept with the entry)")],
) -> None:
    """Correct an entry that is still pending review; it stays pending and keeps its previous version."""
    import yaml

    from bankrec.tracker.manual import ManualCampaignIn, amend

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    with _session() as s:
        row = amend(s, entry_id, ManualCampaignIn.model_validate(data), by=by, reason=reason, now=_now())
        s.commit()
        typer.echo(f"entry {row.id}: amended, still pending review")


@offers_app.command("evidence")
def offers_evidence(
    out: Annotated[Path, typer.Option(help="Markdown file to write the comparison tables to")],
    entry: Annotated[list[int] | None, typer.Option(help="entry ids (default: every pending entry)")] = None,
) -> None:
    """Review evidence for pending manual entries: each stored field next to the official page's words, read now
    from the official page (robots.txt and rate limits apply). Read-only: nothing is stored, published or approved."""
    from datetime import UTC
    from datetime import datetime as dt

    from bankrec.db import staging as S
    from bankrec.ingest.common.html import parse_html
    from bankrec.ingest.fetch import Fetcher
    from bankrec.tracker import evidence as E

    settings = get_settings()
    reg = load_registry()
    with _session() as s:
        rows = list(s.scalars(select(S.ManualCampaignEntry).where(S.ManualCampaignEntry.state == "pending_review")
                              .order_by(S.ManualCampaignEntry.id)))  # fmt: skip
        rows = [r for r in rows if not entry or r.id in entry]
        payloads = [(r.id, r.payload) for r in rows]
    fetcher = Fetcher(settings)
    renderer = None
    parts = [
        "# Pending manual entries: stored values vs. official pages",
        "",
        f"Generated {dt.now(UTC):%Y-%m-%d %H:%M} UTC by `bankrec offers evidence` (read-only; robots.txt and the rate"
        " limit applied). Nothing was approved; the owner reviews each entry.",
        "",
    ]
    shared: dict[str, Any] = {}

    def get_browser() -> Any:  # one browser for the whole command
        if "browser" not in shared:
            from playwright.sync_api import sync_playwright

            shared["ctx"] = sync_playwright().start()
            shared["browser"] = shared["ctx"].chromium.launch(
                headless=True, executable_path=settings.chromium_executable
            )
        return shared["browser"]

    try:
        for eid, payload in payloads:
            e = E.entry_of(payload)
            src = next(
                (
                    x
                    for x in reg.sources
                    if str(x.source_url).split("?")[0].rstrip("/") == e.source_url.rstrip("/")
                ),
                None,
            )
            how, text, at = "", "", None
            if src is None and e.source_kind == "third_party":
                text, at, how = E.read_third_party(e, fetcher, settings, get_browser)
            elif src is None:
                how = "no registered source for this URL: not fetched, entry stays pending"
            else:
                bank = reg.bank(src.bank_id)
                if src.requires_render:
                    if renderer is None:
                        from bankrec.ingest.render import Renderer

                        renderer = Renderer(settings, get_browser(), fetcher.robots, fetcher.limiter)
                    fr = renderer.render(src, bank)
                    how = "rendered in a browser (as the pipeline does for this page)"
                else:
                    fr = fetcher.fetch(src, bank)
                    how = "plain HTTP GET"
                if fr.failure is not None:
                    how += f" — FAILED ({fr.failure.value}: {fr.detail[:80]}); entry stays pending"
                else:
                    text, at = parse_html(fr.body.decode("utf-8", errors="replace")).text, fr.retrieved_at
                    how += f", HTTP {fr.status}"
            if text:
                parts.append(E.markdown(eid, e, E.compare(e, text), e.source_url, how, at))
            else:
                parts.append(f"### Entry {eid}: `{e.card_key}`\n\nSource: {e.source_url} · {how}\n")
            typer.echo(f"entry {eid}: {how}")
    finally:
        if "ctx" in shared:
            shared["browser"].close()
            shared["ctx"].stop()
        fetcher.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    typer.echo(f"written: {out}")


@offers_app.command("merge-duplicates")
def offers_merge_duplicates(
    apply: Annotated[bool, typer.Option(help="make the changes (default: only list them)")] = False,
) -> None:
    """Fold campaigns created from approved manual entries into the same current offer that was already tracked."""
    from bankrec.tracker.manual import merge_duplicates

    with _session() as s:
        done = merge_duplicates(s, now=_now(), apply=apply)
        if apply:
            s.commit()
    for line in done or ["nothing to merge"]:
        typer.echo(line)
    if done and not apply:
        typer.echo("dry run: re-run with --apply to merge")


@offers_app.command("pending")
def offers_pending() -> None:
    """List hand-entered campaigns waiting for review."""
    from bankrec.tracker.manual import pending

    with _session() as s:
        for r in pending(s):
            typer.echo(
                f"{r.id}\t{r.card_key}\t{r.channel}\t{r.source_kind}\tby {r.entered_by} {r.entered_at:%Y-%m-%d}"
                f"\t{r.source_url}"
            )


@offers_app.command("approve")
def offers_approve(entry_id: int, reviewer: Annotated[str | None, typer.Option()] = None) -> None:
    """Approve a pending entry: it becomes a campaign (with its status logged)."""
    from bankrec.tracker.manual import approve

    with _session() as s:
        c = approve(s, entry_id, reviewer=_reviewer(reviewer), now=_now())
        s.commit()
        typer.echo(f"campaign {c.id} ({c.status})")


@offers_app.command("reject")
def offers_reject(
    entry_id: int,
    note: Annotated[str, typer.Option()],
    reviewer: Annotated[str | None, typer.Option()] = None,
) -> None:
    from bankrec.tracker.manual import reject

    with _session() as s:
        reject(s, entry_id, reviewer=_reviewer(reviewer), note=note, now=_now())
        s.commit()


@offers_app.command("set-status")
def offers_set_status(
    campaign_id: str,
    status: Annotated[
        str, typer.Argument(help="active | ending_soon | expired | withdrawn | pending_verification | stale")
    ],
    reason: Annotated[str, typer.Option(help="why (logged with your name)")],
    reviewer: Annotated[str | None, typer.Option()] = None,
) -> None:
    """A reviewer's status decision, e.g. withdrawn after the bank confirmed it ended."""
    from bankrec.tracker.manual import set_status

    with _session() as s:
        set_status(s, campaign_id, status, reviewer=_reviewer(reviewer), reason=reason, now=_now())
        s.commit()


@offers_app.command("verify-rules")
def offers_verify_rules() -> None:
    """Check that every page-captured rule and valuation excerpt is still in its page's latest capture."""
    from bankrec.tracker.verify import verify_excerpts

    with _session() as s:
        problems = verify_excerpts(s)
    for p in problems:
        typer.echo(p)
    typer.echo(f"{len(problems)} problem(s)")
    if problems:
        raise typer.Exit(1)
