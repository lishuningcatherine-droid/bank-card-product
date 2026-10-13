# Final audit — limitations and manual-review items

Date: 2026-10-13. Branch `claude/blissful-feynman-qua5w1`.

## What was verified in this environment

| Check | Result |
|---|---|
| Python lint (`ruff check`, `ruff format --check`) and typecheck (`mypy`, 85 files) | pass |
| Python tests (`pytest`, real PostgreSQL 16) | **224 passed, 5 skipped** (the 5 real-bank verbatim-fixture tests, pending) |
| Coverage of `parsers`, `normalize`, `validation`, `dedup`, `recommend`, `freshness` | **93%** (target 85%) |
| Web lint, typecheck (TS strict), Vitest | pass; **66** unit tests |
| Web production build (Next.js 16.4) | pass |
| Playwright E2E incl. axe (WCAG 2.1 A/AA) on 16 pages, 375/768/1280 px layouts, keyboard | **28 passed** |
| Migrations up → down → up; read-only API role denied on `staging` | pass |
| Reachability survey through the real fetcher | every bank and CFPB domain `ENV_NETWORK_BLOCKED` |
| Docker images and `docker compose` stack | Not buildable in this sandbox (Docker Hub `429`). **Verified in CI**: the `docker` job builds the api, web and worker images and smoke-tests the compose stack (run 38345207939, green) |
| GitHub Actions CI | **All green** on `ef7a840` (run 38345207939): web, python (3.12), python (3.13), e2e, docker |

## Acceptance criteria status (brief §20)

| # | Criterion | Status |
|---|---|---|
| 1 | Runs locally via documented commands | Native path verified here (uv, pnpm, Postgres). Compose path verified by the CI `docker` job |
| 2 | Builds, lint, typecheck pass | Yes |
| 3 | All tests pass, including E2E | Yes (5 real-bank fixture tests skipped as pending, by design) |
| 4–5 | Five banks and three product types supported structurally | Yes (configs, adapters, schema, API, UI). **No real data** |
| 6 | User-facing data only from `prod` | Yes (read-only role; repository reads `prod` only) |
| 7 | Unverified, stale, targeted, expired and recheck-pending offers hidden from recommendations | Yes (request-time `offer_state`; tests) |
| 8 | Every displayed offer has a source and verification date | Yes |
| 9 | Expired offers excluded or labeled | Yes (server and browser re-check) |
| 10 | No duplicates in recommendations | Yes (canonical key; fuzzy matches go to review) |
| 11 | No product named `unknown` | Yes (rule `R-NAME` plus a DB CHECK constraint) |
| 12 | Every production field has provenance | Yes (span-guarded `Sourced` values; tested) |
| 13–16 | Explained scores; first-year/ongoing/multi-year split; achievability test; savings rules | Yes |
| 17 | Example Bank added via the documented process only | Yes |
| 18 | UI follows DESIGN_SYSTEM, responsive, passes axe | Yes (token guard test; E2E) |
| 19 | README matches the system | Yes |
| 20 | This file | Yes |
| 21 | Docker production build runs, CI green | Yes: CI run 38345207939 is green on all five jobs, including the Docker image builds and the compose smoke test |
| 22 | REACHABILITY.md exists and the registry matches it | Yes (all real banks: zero sources, availability `unknown`) |

## Remaining limitations

1. **No real product data.** All five bank domains and `consumerfinance.gov` were refused by this session's egress
   proxy, even after the owner changed the allowed domains (the policy most likely applies only to new sessions). The
   production dataset is empty. The 30–50 verified cards target is not met. Nothing was substituted.
2. **Real-bank adapters are unverified.** They use the shared extractors and the owner's pre-survey notes, tested on
   synthetic Example Bank pages only. Selectors and labels must be checked against verbatim pages before enabling sources.
3. **CFPB column mapping is unconfirmed** (`config/regulators/cfpb_tccp.yaml`). Files that don't match fail loudly
   (`SCHEMA_DRIFT`). Dataset URLs are not configured.
4. **Docker** could not run in this sandbox (Docker Hub rate limit). It is verified only in CI.
5. **CSP uses `'unsafe-inline'` scripts** (no nonces) so pages can be cached. There are no third-party scripts.
6. **Single web replica.** Horizontal scaling needs a shared Next.js cache handler.
7. **Rate limiting is in-process** (one API replica). Multiple replicas need a shared store (e.g. Redis) or a
   gateway limit.
8. **Heuristics to review on real pages:** segment derived from "Business" in the name; co-brand detection via
   `config/co_brands.yaml`; airline/hotel/streaming rates not applied to broad user categories (conservative);
   rotating categories assume 25% of spend when the user opts in (configurable and disclosed).
9. robots.txt matching is implemented in `bankrec.ingest.robots` (RFC 9309: `*`/`$` wildcards, longest match,
   Allow wins ties) because Python 3.12's `urllib.robotparser` silently ignores wildcards. That was found by CI on
   Python 3.12 and is covered by `tests/unit/test_robots.py` on 3.12 and 3.13.
10. The fetcher treats an unreadable robots.txt as unreachable, so a site whose robots.txt is blocked can only be
   captured manually.

## Manual-review / owner actions

| Item | Action |
|---|---|
| Network access | Start a new session (or run locally) with the allowed domains, then `bankrec survey` |
| Real sources | Confirm 2–3 official URLs per bank × type; add them to `config/sources/<bank>.yaml`; save verbatim fixtures + `RETRIEVED.txt`; un-skip adapter tests |
| Product-type availability | Replace `unknown` with `offered`/`not_offered` plus evidence URLs in each bank config |
| CFPB | Confirm the TCCP and agreements URLs and the column mapping |
| Contact email | Set `BANKREC_CONTACT_EMAIL` locally (placeholder in `.env.example`) |
| Secrets | Generate `REVALIDATE_SECRET`, DB passwords, optional webhook secret |
| Review queue | After the first real ingestion: `bankrec review list` (fuzzy duplicates, comparison-page candidates, conflicts) |
| CI | Green as of `ef7a840`. Keep it green; actions still target Node 20 (deprecation warning only) |
