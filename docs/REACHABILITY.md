# Reachability survey (brief §6.2)

**Survey run:** 2026-10-13 08:54 UTC, by `bankrec survey` on the owner's machine (normal internet access).
**Raw output:** [`docs/reachability/survey-2026-10-13.json`](reachability/survey-2026-10-13.json). The previous
cloud-session survey (every domain refused by that session's egress proxy) is kept as
[`survey-2026-10-12.json`](reachability/survey-2026-10-12.json).
**User-Agent:** `bankrec/0.1.0 (+https://github.com/lishuningcatherine-droid/bank-card-product; <BANKREC_CONTACT_EMAIL>)`.
`BANKREC_CONTACT_EMAIL` was still the placeholder `contact@example.invalid` for this run (owner to set).

## robots.txt and sitemaps

| Host | robots.txt | Notes |
|---|---|---|
| `creditcards.chase.com` | 200 | `User-agent: * / Disallow:` (allows all). Sitemap: 91 URLs. |
| `www.chase.com` | 200 | Disallows `/online/…`, `/ccpmweb/…`, the legacy locator sitemap and others. Sitemap index (5,000+ URLs). |
| `sites.chase.com` | 200 | **`User-agent: * / Disallow: /`** — Pricing & Terms pages cannot be fetched. Also names AI crawlers explicitly. |
| `www.capitalone.com` | 200 | `*` group disallows only `/cars/idplogin`, `/cars/prequalify?`, `/cars/search?filters=ey`. Sitemap index → `credit-cards/sitemap.xml` (88 URLs), `small-business/sitemap.xml`. |
| `card-apis.capitalone.com` | **403** | Treated as disallow-all (DESIGN §24.5). Card pages load their data from `/protected/…/product/` here. |
| `www.bankofamerica.com` | 200 | Sitemap index `content/sitemap_index.xml`. |
| `www.usbank.com` | 200 | Lists `site-map.xml` (3,336 URLs) and three location/advisor sitemaps. |
| `www.americanexpress.com` | 200 | `index-sitemap.xml` (per-country sitemaps). |
| `www.consumerfinance.gov` | 200 | `sitemap.xml` (5,000+ URLs). |

## Bank × product type

| Bank | Credit cards | Checking | Savings |
|---|---|---|---|
| Chase | **Static HTML, 200.** 42 card pages from the card sitemap; 38 single-card product pages registered (`product_detail`, `has_offers` → rendered). Annual fee, APR, earn rates and welcome offer are in the static HTML; rendering gives the same content (2 of 38 renders timed out on `networkidle`). Pricing & Terms on `sites.chase.com`: **robots-disallowed**. | Offered (sitemap lists `personal/checking/total-checking`, `premier-plus-checking`, `high-school-checking`; offers on `personal/offers/total-checking-300`). Not yet ingested. | Not surveyed yet. |
| Capital One | In progress | | |
| Bank of America | Pending | | |
| U.S. Bank | Pending | | |
| American Express | Pending | | |

## Pre-survey findings checked against real pages

| Finding (owner's notes) | Observed 2026-10-13 |
|---|---|
| Chase card pages are fully static | **Confirmed** for all 42 card pages fetched. |
| `creditcards.chase.com` robots allows all | **Confirmed.** |
| `www.chase.com` disallows education paths and `/content/dam/chase-ux/ratesheets/` | Not re-checked line by line; the fetcher applies the live file on every run. |
| Checking bonuses on separate `/personal/offers/…` pages | **Confirmed** in the sitemap (`/personal/offers/total-checking-300`). |
| Card terms on `sites.chase.com` | **Confirmed, and that host disallows all crawlers.** |
