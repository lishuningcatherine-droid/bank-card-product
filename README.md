# Bank Product Recommendation Platform (v2)

## Purpose

Helps people discover and compare **publicly available** U.S. credit cards, checking accounts, and savings accounts
from Bank of America, Chase, Capital One, U.S. Bank, and American Express, and get **deterministic, explained**
recommendations from broad, anonymous inputs.

The platform reads official bank pages only. Every published value traces back to the quoted text it came from
in a stored snapshot. It never logs in, never handles credentials or account data, has no affiliate links, and never
presents data as real-time.

> **Current data status:** the build environment could not reach any bank domain (egress policy refusal; see
> [docs/REACHABILITY.md](docs/REACHABILITY.md)). The pipeline, API, and UI are complete and tested, but **the
> production dataset is empty** until ingestion runs where the bank sites are reachable. All demo data, tests,
> screenshots, and E2E runs use the fictional **Example Bank** (`test_only`, clearly labeled).

## Architecture

```
config/ (YAML registry, scoring, freshness, change policy)
   │
worker: bankrec ingest ──► retrieve (robots, ≥3 s/host, honest UA; Playwright fresh context for offers)
   │                        ► snapshot (raw + text hashes) ► change detection ► classify ► adapter extract
   │                        ► normalize ► validate ► canonical identity / dedup ► review queue ► publish (versions)
   │                        ► reports ► revalidation outbox ──► signed POST to web /api/internal/revalidate
   ▼
PostgreSQL 16:  staging (pipeline, provenance, review, history)   prod (published records only)
   ▲                                                                ▲ read-only role
api (FastAPI /api/v1) ── recommend engines (pure, config-driven) ───┘
   ▲
web (Next.js 16 App Router, server-rendered listings and detail pages, tag-based cache)
```

Details: [docs/DESIGN.md](docs/DESIGN.md) (§1–§23), [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md),
[docs/AUDIT.md](docs/AUDIT.md), [docs/REACHABILITY.md](docs/REACHABILITY.md), [docs/TRACE.md](docs/TRACE.md),
[docs/FINAL_AUDIT.md](docs/FINAL_AUDIT.md).

| Path | Contents |
|---|---|
| `src/bankrec/` | Python package: `registry`, `ingest` (fetch, render, snapshot, adapters, pipeline), `classify`, `parsers`, `normalize`, `validation`, `dedup`, `publish`, `freshness`, `crosscheck`, `review`, `reports`, `recommend`, `api`, `cli` |
| `config/` | Bank and source registry, adapter rules, scoring, point values, freshness, change policy, validation, CFPB column mapping, providers |
| `migrations/` | Alembic (`staging` + `prod` schemas, read-only API grants) |
| `web/` | Next.js frontend, Vitest unit tests, Playwright E2E |
| `tests/` | pytest: unit, adapters, integration (PostgreSQL), API |
| `docker/`, `docker-compose*.yml` | Images (non-root) and stacks |
| `legacy/` | Archive area (empty: no v1 files existed). Production code may not import it |

## Setup

Requirements: Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm 10, PostgreSQL 16 (or Docker).

```bash
cp .env.example .env              # fill in secrets; BANKREC_CONTACT_EMAIL is a placeholder until you set it
uv sync                           # Python deps from uv.lock
pnpm -C web install               # web deps from pnpm-lock.yaml
```

With Docker (local stack, including Example Bank test data):

```bash
docker compose up -d --build db migrate api web
docker compose --profile tools run --rm worker-once   # ingests Example Bank (test_only) — dev only
# web: http://localhost:3000   api: http://localhost:8000/api/v1/docs
```

Run `NEXT_PUBLIC_TEST_DATA_BANNER=1 docker compose up …` to show the test-data banner, and set `E2E_TEST_DATA=1` on
the API to serve `test_only` data in dev.

## Development commands

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
uv run mypy
uv run pytest                                   # needs PostgreSQL at TEST_DATABASE_URL
uv run bankrec api serve --port 8000            # API
pnpm -C web dev                                 # web (NEXT_PUBLIC_API_BASE_URL, API_INTERNAL_URL)
pnpm -C web lint && pnpm -C web typecheck && pnpm -C web test && pnpm -C web build
uv run bankrec api openapi && pnpm -C web gen:api   # regenerate OpenAPI spec and TypeScript types
```

## Database initialization and migrations

```bash
psql "$SUPERUSER_URL" -f deploy/db/roles.sql    # once: read-only API role (compose does this via init-roles.sh)
uv run bankrec db upgrade                       # Alembic migrations (run on every deploy)
uv run bankrec db export-prod prod.jsonl        # export published prod data (JSONL)
uv run bankrec db seed prod.jsonl               # load published data only; refuses test_only data without --include-test
```

**Backup and restore:** `pg_dump -Fc -n prod -n staging "$DATABASE_URL" > bankrec.dump` and
`tar czf raw.tgz data/raw` (snapshots back the provenance). Restore with `pg_restore -d "$DATABASE_URL" bankrec.dump`
and extract the tarball into `data/raw`.

## Ingestion commands

```bash
uv run bankrec survey                           # reachability: robots.txt + sitemaps per bank
uv run bankrec discover --bank chase            # sitemap URLs → config/sources/chase.discovered.yaml (never enabled)
uv run bankrec ingest                           # all enabled sources (fails loudly if the registry is empty)
uv run bankrec ingest --tier apy|offer|terms|regulator_release
uv run bankrec ingest --bank capital_one --no-render
uv run bankrec ingest --manual data/manual_snapshots/chase/sapphire.html --source-url <url> --captured-at 2026-10-12
uv run bankrec crosscheck tccp release.csv --release-id 2026H1 --as-of 2026-06-30   # CFPB cross-check only
```

Every run writes `reports/<run_id>/` (CSV + Markdown + `summary.md`): retrieval failures, classifications, parser
errors and regressions, missing fields, conflicts, duplicates, rejected records, review items, published, stale,
expired offers, recheck-pending, cross-check results, recommendation-ready, counts by bank × type × status, and
`manual_verification_needed`. Every registry source appears with a terminal status.

## Adding a bank

See [docs/ADDING_A_BANK.md](docs/ADDING_A_BANK.md): bank config + sources config + adapter (copied from
`_template.py`, mostly declarative rules) + fixtures + tests. No other code changes. Example Bank proves this.

## Adding a source

Add an entry to `config/sources/<bank_id>.yaml` with `slug`, `product_type`, canonical official `source_url`,
`source_kind` (`product_detail`, `offer_detail`, `comparison`, `listing`, `terms_pdf`, `manual_snapshot`,
`regulator_dataset`, `licensed_data_provider`), `parser_name`, `expected_entity`, and optionally `refresh_tier`,
`requires_render`, `has_offers`, `render_ready_selector`, `expand_selectors`. Run `uv run bankrec registry validate`:
empty, malformed, duplicate, tracking or referral, and non-official URLs fail loudly.

## Validation

Products are `valid`, `needs_review`, or `reject`, using named rules recorded in `staging.validation_results`
(`R-NAME`, `R-DOMAIN`, `R-PAGE`, `R-DETAIL`, `R-REQ`, `R-CAPTURE`, `V-QUALIFIER`, `C-*` consistency, `X-CONFLICT`,
`F-FRESH`, `R-CONFIDENCE`). Thresholds and required/key fields are in `config/validation.yaml`. Products and offers are
validated independently. User-facing labels are **Verified** (recommendable) and **Partially verified** (browse and
compare only, with the missing items listed). Under-review records are never served.

## Reviewing uncertain records

```bash
export BANKREC_REVIEWER="Your Name"
uv run bankrec review list [--type credit_card] [--bank chase]
uv run bankrec review show <id>                 # snapshot excerpt, values + evidence, conflicts, dedup proposal
uv run bankrec review approve <id> --note "confirmed on official page"
uv run bankrec review reject <id> --reason "extraction error"
uv run bankrec review merge <canonical_key_a> <canonical_key_b> --note "same product"
uv run bankrec review edit <id> --field monthly_fee_cents --value 0 --evidence "Monthly fee $0"
```

Edits are refused unless the quoted evidence exists in a stored snapshot. Every action is logged in
`staging.review_decisions`.

## Publishing

`valid` records publish automatically. Changes to published records follow `config/change_policy.yaml`: APY within
±0.25 pp and uniform APR shifts within ±0.50 pp publish as a new version; any other change (fees, rewards,
bonuses, requirements, offers appearing or disappearing) goes to review while the old value stays visible as
"Recheck pending" and is excluded from recommendations. Each publish writes `product_versions` / `offer_versions` and
queues signed revalidation of the affected pages (`bankrec revalidate dispatch`).

## Freshness schedules

`config/freshness.yaml`: APY sources every 12 h, offers daily, terms weekly, CFPB release check daily. Staleness
windows are offers 14 days, APY 7 days, terms 60 days, measured from the last check that confirmed the value. The worker
container runs `bankrec schedule crontab` under supercronic. `.github/workflows/scheduled-ingest.yml` is the
alternative. `BANKREC_SCHEDULER=worker|github|off` selects one, and per-tier advisory locks prevent overlap.
`bankrec report stale` lists what is due.

## Scoring

Deterministic, with no ML. Weights are in `config/scoring.yaml` and point values in `config/point_values.yaml`
(default 1.0¢, adjustable by the user). Both are served by `GET /api/v1/methodology`. Values are always split into
ongoing annual, promotional (exact and achievable only; "up to" and "at least" count $0), first-year, and a 3-year
view, with a break-even line for fee cards. Checking results show the direct-deposit achievability test. Savings
results apply the deposit and holding-period rules. Every result returns a per-component score breakdown and reasons.

## Tests

```bash
uv run pytest                          # 224 passed, 5 skipped (real-bank verbatim-fixture tests pending)
pnpm -C web test                       # Vitest: design tokens, wording ban, offer wording, signatures, …
cd web && NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010 NEXT_PUBLIC_TEST_DATA_BANNER=1 pnpm build \
       && pnpm exec playwright test    # 28 E2E tests incl. axe on every major page; starts a seeded API itself
SCREENSHOTS=1 pnpm -C web exec playwright test screenshots   # regenerates docs/screenshots
```

Coverage on `parsers`, `normalize`, `validation`, `dedup`, `recommend`, `freshness` is **93%** (CI gate 85%).

## Deployment

Build images (`docker/api.Dockerfile`, `docker/web.Dockerfile` with build arg `NEXT_PUBLIC_API_BASE_URL`,
`docker/worker.Dockerfile`), push them, set the variables from `.env.example`, and run
`docker compose -f docker-compose.prod.yml up -d` on any container host (managed PostgreSQL works too: point
`DATABASE_URL`/`API_DATABASE_URL` at it). The web app can also be deployed to any Node host or Vercel with the same env.

- Migrations run in the one-shot `migrate` service on every deploy.
- The API uses a read-only role over `prod`. CORS is locked to `WEB_ORIGIN`, with security headers, POST rate limits
  and body-size limits. Docs are disabled and HSTS is on in production.
- **v1 runs one web replica.** Tag revalidation updates that replica's cache. Before scaling web horizontally, configure
  a shared Next.js `cacheHandler` (for example Redis), otherwise replicas serve stale pages until their 1-hour fallback.
- Optional error tracking: set `SENTRY_DSN` (off by default). Logs are structured JSON without request bodies.

## Known limitations

See [docs/FINAL_AUDIT.md](docs/FINAL_AUDIT.md). In short: no real bank or CFPB data could be retrieved from the build
environment, so the production dataset is empty and the five real-bank adapters are unverified against real pages.
Docker images could not be built here (Docker Hub rate limit) and are verified in CI only.
