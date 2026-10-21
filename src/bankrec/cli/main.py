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
events_app = typer.Typer(no_args_is_help=True, help="Consented anonymous ranking events (DESIGN §26.7).")
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
    from bankrec.schedule import try_lock, unlock

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
    lock_conn = engine.connect()
    lock_tier = tier or "all"
    if not try_lock(lock_conn, lock_tier):
        typer.echo(f"skipped: tier {lock_tier} already running")
        lock_conn.close()
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
            s.commit()
            out = write_reports(s, result, reg, settings.reports_dir, _now())
            s.commit()
            from bankrec.revalidate import dispatch

            dispatch(s, settings, _now())
            s.commit()
        typer.echo(json.dumps({"run_id": result.run_id, "reports": str(out), **p.counts()}, indent=1))
        if reg.banks_without_sources and not include_test and not manual:
            typer.echo(
                f"warning: banks without enabled sources: {', '.join(reg.banks_without_sources)}", err=True
            )
    finally:
        fetcher.close()
        if browser_ctx is not None:
            browser_ctx.stop()
        unlock(lock_conn, lock_tier)
        lock_conn.close()


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
