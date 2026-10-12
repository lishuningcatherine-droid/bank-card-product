# Phase 1 — Audit of the existing system

**Date of audit:** 2026-10-12
**Repository:** `lishuningcatherine-droid/bank-card-product` (GitHub), checked out at `/home/user/bank-card-product`
**Auditor:** Claude Code (automated session)

## 0. Summary

The repository is **empty**. It has no commits, no branches on the remote, and no files. None of the legacy
files listed in §4 of the build brief exist here, so there is no code, data, schema, test, scraper, or UI to
audit, reuse, or archive.

All of the "known historical failures" in the brief (about 290 extracted cards, about 12 recommendation-ready, 281
"duplicates", and so on) are **therefore unverifiable from this repository**. This audit records them as
reported context and does not confirm them.

The environment also blocks outbound access to every bank domain (see §9). That decides what Phase 4
and Phase 7 can deliver from this environment.

## 1. Evidence

| Check | Command / tool | Result |
|---|---|---|
| Local working tree | `find . -path ./.git -prune -o -type f -print` | no files |
| Local history | `git log` | `fatal: your current branch ... does not have any commits yet` |
| Remote refs | `git ls-remote origin` | no output (no refs) |
| Remote branches | GitHub API `list_branches` | `[]` |
| Other repos on account | `list_repos` | `bank-card-product`, `rocket`, `Financial-time-series`, `pic16b_finalproject`; none named as holding the legacy system, and I did not search them (out of scope without your say-so) |

## 2. Legacy file checklist (§4 of brief)

| File | Exists? |
|---|---|
| `data/sources.csv` | No |
| `data/cards.csv` | No |
| `data/master_credit_cards.csv` | No |
| `data/cards_raw.csv` | No |
| `data/cards_production.csv` | No |
| `data/cards_with_field_confidence.csv` | No |
| `data/discovered_sources.csv` | No |
| `data/validation_report.csv` | No |
| `data/duplicate_review.csv` | No |
| `data/manual_review_queue.csv` | No |
| `data/manual_audit_notes.csv` | No |
| `data/recommendation_ready_cards.csv` | No |
| `data/rejected_products.csv` | No |
| `data/manual_sources.csv` | No |
| `data/card_feature_matrix.csv` | No |

Row counts and good/bad row samples: **not possible**, because there are no datasets.

## 3. Architecture, files, frontend, backend
None present. The brief describes the previous workflow as
`sources.csv → scraper/discovery → parser → validation → deduplication → normalized dataset → recommender → frontend`,
but the repository contains no implementation of any stage.

## 4. Schema
None present (no SQL, ORM models, migrations, or CSV headers).

## 5. Scrapers and parsers
None present.

## 6. Tests
None present.

## 7. Recommendation logic
None present.

## 8. UI
None present.

## 9. Environment constraints found during the audit

| Item | Finding | Impact |
|---|---|---|
| Python | 3.13.16 available; `uv` and `poetry` installed | Meets the brief's "3.12+" requirement; use `uv` |
| Node / pnpm | Node 22.22.0, pnpm installed | Fine for Next.js |
| PostgreSQL | Local PostgreSQL 16.15 cluster, started successfully | DB tests can run against real Postgres here |
| Docker | CLI present, **daemon not available** | Cannot run `docker compose up`, testcontainers, or production image builds in this session. Compose files and Dockerfiles can be written, but they can only be *verified* in CI (GitHub Actions) or on your machine |
| Playwright | Chromium pre-installed at `/opt/pw-browsers` | E2E, axe, and screenshots are feasible |
| **Outbound network to banks** | `robots.txt` fetch through the session's egress proxy returned **HTTP 403 (CONNECT rejected by organization policy)** for `www.bankofamerica.com`, `www.chase.com`, `creditcards.chase.com`, `www.capitalone.com`, `www.usbank.com`, and `www.americanexpress.com` (and `example.com`). Only package registries are allowed. | **A real ingestion against official sources cannot run from this session.** I also cannot obtain verbatim official fixtures. Per the honesty rules, I will not substitute any data. |

## 10. What is reusable
Nothing. There is no existing code or data.

## 11. Broken or misleading pieces
None in the repo. The root problems listed in §4 of the brief (empty or malformed `sources.csv` producing zero records,
landing pages used as sources, blocked pages parsed as products, URL-as-identity dedup, unmodeled offers,
stale or expired offers, opaque scoring) are treated as **design requirements** in `docs/DESIGN.md`. Each one is mapped
to a specific control there (§12 of DESIGN.md).

## 12. Missing dependencies
Everything still has to be written. On the system side, only the Docker daemon is missing in this environment (see §9).

## 13. Security and privacy issues
None in the repo, since it is empty. Nothing secret is committed. DESIGN.md covers privacy controls for the new build.

## 14. Consequences for the plan

1. **Phase 2 (isolate legacy)** has nothing to move. I create `legacy/data/` and `legacy/src/` with READMEs saying
   they are empty and why, so that you can drop legacy files there later, and I add the import guard anyway.
2. **Phase 4 / Phase 7 real ingestion:** blocked from this session by the egress policy. Options are listed in
   DESIGN.md §14: (a) allow the five bank domains in the environment's network settings, (b) run `bankrec ingest`
   on your machine, or (c) use the manual-capture workflow (§6.4), where you save official pages into
   `data/manual_snapshots/`.
3. **Real-bank adapter tests** must be marked *pending* (with reasons) until verbatim official fixtures exist. Adapter logic
   is covered with synthetic **Example Bank** fixtures, which are clearly fictional.
4. **The production dataset will be empty** until (2) is resolved. The UI and API are built to show honest empty states
   rather than placeholder products.
