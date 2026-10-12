# Reachability survey (brief §6.2)

**Survey run:** 2026-10-12 23:07 UTC, by `bankrec survey` from the cloud build environment.
**Raw output:** [`docs/reachability/survey-2026-10-12.json`](reachability/survey-2026-10-12.json)
**User-Agent:** `bankrec/0.1.0 (+https://github.com/lishuningcatherine-droid/bank-card-product; <BANKREC_CONTACT_EMAIL>)`

## Result: every domain was refused by the build environment's egress proxy

The environment's network setting was changed to allow `*.chase.com`, `static.chasecdn.com`, `*.capitalone.com`,
`*.bankofamerica.com`, `*.americanexpress.com`, `*.usbank.com`, and `*.consumerfinance.gov`. Even so, every request from this
session was refused **before reaching the bank**. The session's proxy answered `403` to the HTTPS `CONNECT`
(`connect_rejected: the egress proxy denied the CONNECT (organization policy)`). The banks never saw these requests, so
nothing here says anything about the banks' own bot protection.

Most likely cause: the session was started before the policy change, so a new session (or the owner running
`bankrec survey` locally) is needed for the change to apply. Per the brief, I did not retry in a loop and did not
try to work around the block.

| Bank | robots.txt | Sitemaps | Failure |
|---|---|---|---|
| American Express | `https://www.americanexpress.com/robots.txt` refused | `index-sitemap.xml` not attempted (robots unknown) | `ENV_NETWORK_BLOCKED` |
| Bank of America | `https://www.bankofamerica.com/robots.txt` refused | `content/sitemap_index.xml` not attempted | `ENV_NETWORK_BLOCKED` |
| Capital One | `https://www.capitalone.com/robots.txt` refused | `sitemap.xml` not attempted | `ENV_NETWORK_BLOCKED` |
| Chase | `https://www.chase.com/robots.txt` and `https://creditcards.chase.com/robots.txt` refused | both sitemaps not attempted | `ENV_NETWORK_BLOCKED` |
| U.S. Bank | `https://www.usbank.com/robots.txt` refused | none listed (robots unread) | `ENV_NETWORK_BLOCKED` |
| CFPB | `https://www.consumerfinance.gov/robots.txt` refused | n/a | `ENV_NETWORK_BLOCKED` |

The fetcher treats an unreadable robots.txt as **unreachable**, never as "allowed". So no sitemap or product page was
requested after the robots.txt failure.

## Bank × product type

The brief asks for, per bank × type: HTTP result, robots result, fields present statically vs. only after rendering,
the recommended `source_kind` and `requires_render`, and blockers. **None of this could be observed.** The registry
reflects that: every real bank has `availability: unknown` and **zero sources**
(`config/sources/<bank>.yaml: sources: []`). No URL was guessed.

| Bank | Credit cards | Checking | Savings | Recommended settings once reachable (from owner's pre-survey; unverified) |
|---|---|---|---|---|
| Chase | not surveyed | not surveyed | not surveyed | Card pages `product_detail`, static. Checking bonuses: `offer_detail` on `/personal/offers/…` (render). Card terms: `terms_page` on `sites.chase.com`. Robots: avoid education paths and `/content/dam/chase-ux/ratesheets/`. |
| Capital One | not surveyed | not surveyed | not surveyed | Cards static. Savings APY `requires_render: true` (static HTML shows `NaN`). |
| Bank of America | not surveyed | not surveyed | not surveyed | Cards static; hidden "temporarily unavailable" boilerplate is configured in `boilerplate_phrases`. Do not fetch `/deposits/*.pdf` (robots). |
| American Express | not surveyed | not surveyed | not surveyed | Product pages static for earn/caps/credits/fee (FAQ). Welcome offers and savings APY need `requires_render: true`. Discover via sitemap (listing page is a JS shell). Never fetch `/*/apply/`. |
| U.S. Bank | not surveyed | not surveyed | not surveyed | Cards static for name/bonus/rates/caps. APR needs `requires_render: true` (static shows a bare `$`). Read robots.txt first. |

## Pre-survey findings encoded as tests

These come from the owner's notes and **were not observed here**. They are encoded as behaviour tests on **synthetic**
pages, so the pipeline handles them correctly once real pages arrive:

| Finding | Test |
|---|---|
| BoA hidden "temporarily unavailable" boilerplate must not make a product page "blocked" | `tests/unit/test_classifier.py::test_hidden_boilerplate_is_still_a_product_page` |
| Capital One APY shows `NaN` statically → missing with reason `requires_render` | `tests/unit/test_placeholders.py`, `tests/integration/test_pipeline.py::test_placeholder_apy_is_requires_render` |
| U.S. Bank APR shows a bare `$` → missing with reason `requires_render` | `tests/unit/test_extract.py::test_bare_dollar_apr_is_requires_render` |
| Amex welcome offer absent statically → no offer record + "Check American Express…" note; fee from FAQ answer | `tests/adapters/test_american_express.py` |
| Chase/Amex/BoA robots disallow rules are obeyed, including for XHR paths | `tests/unit/test_fetch.py::test_robots_*` (synthetic robots.txt, labeled as such) |

## What remains (owner action)

1. Start a **new session** (so the allowed-domain policy applies), or run `bankrec survey` locally. Then re-run this
   survey, and update this file and the registry from the real results.
2. If the survey shows a CDN or terms host outside the allowed list (for example a separate terms or PDF host),
   add exactly that host name to the allowed domains.
3. For each bank and type, confirm 2–3 official product-detail URLs, save verbatim fixtures with `RETRIEVED.txt`
   under `tests/fixtures/<bank_id>/`, and un-skip that bank's adapter tests.
4. Pages that stay blocked go through manual capture (`reports/manual_verification_needed.md`).
