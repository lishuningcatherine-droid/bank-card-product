# Final audit — limitations and manual-review items

Date: 2026-10-13. Branch `claude/blissful-feynman-qua5w1`. Updated after the first real ingestion on the owner's machine.

## Real data (2026-10-13)

Reachability: robots.txt 200 for all five banks and CFPB (`docs/REACHABILITY.md`). Credit cards only; checking and
savings are offered by four of the banks but no deposit sources were added yet.

| Bank | Card sources | Published | **Verified** (recommendation-ready) | Partially verified | In review / not published | Fetch |
|---|---|---|---|---|---|---|
| Chase | 38 (+9 disabled P&T) | 38 | **23** | 15 | — | rendered |
| Capital One | 22 | 21 | **9** | 12 | Quicksilver (no fee in static HTML) | plain HTTP (render blocked by robots on its data API) |
| Bank of America | 22 | 22 | **3** | 19 | — | rendered (static HTML is a shell) |
| U.S. Bank | 11 | 11 | **1** | 10 | — | rendered (static "$" placeholders) |
| American Express | 13 | 12 | **2** | 10 (8 recheck pending) | Platinum (no static name) | plain HTTP (rendering stopped after ~30 loads) |
| **Total** | 106 | 104 | **38** | 66 | | |

The main reason for "Partially verified" is the foreign transaction fee (a key field in `config/validation.yaml`):
most product pages state it only when it is zero, and the issuers' terms pages are robots-disallowed (Chase),
render empty (BoA) or were not located (Capital One, U.S. Bank, Amex).

CFPB TCCP release 2025-12-31 cross-check: 48 plans matched, 89 conflicts (76 APR, 12 balance-transfer fee,
1 annual fee) → review items only; no official value changed or downgraded.

## What was verified on the owner's machine

| Check | Result |
|---|---|
| Python lint, format, mypy (86 files) | pass |
| pytest (real PostgreSQL 16 in Docker) | **280 passed**; adapter tests assert values from 34 verbatim fixtures (5 banks + CFPB release) |
| Web Vitest | 66 passed (web unchanged in this session) |
| Real ingestion runs | 9 runs; every source ended with a terminal status |

## Remaining limitations

1. **Credit cards only.** No checking or savings sources yet (Chase, Capital One and Amex offer both; BoA and U.S. Bank
   not surveyed). Business cards for BoA and Amex not surveyed.
2. **Conservative extraction.** Rates that could be overstated are left out (stacked "total" rates, "up to" rates,
   choice categories, caps that cannot be parsed); see each `docs/adapters/<bank>.md`. Cards can show fewer bonus
   categories than their page, never more.
3. **Welcome offers are missing for Capital One cards whose offer is script-only, and for all Amex cards** (rendering
   blocked/degraded); see `reports/manual_verification_needed.md`.
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
