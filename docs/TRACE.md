# End-to-end trace (brief §17 phase 8)

**Real banks: not traced.** Every bank domain was refused by the build environment's egress policy
(`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md), so no official page could be retrieved. Per the honesty rules, nothing was
substituted. Each real-bank trace stays pending until the owner re-runs ingestion where those domains are reachable.

The trace below follows the **fictional Example Bank** (`test_only`), run through the same production code path. The
only difference is retrieval, which serves a synthetic fixture (`FixtureFetcher`, allowed only for `test_only` banks).
It was produced on 2026-10-13 by `bankrec ingest --include-test --bank example_bank` against a fresh PostgreSQL
database (run `20261013T035058Z-3c9fc5`).

| Hop | Evidence |
|---|---|
| **Official source** | Registry entry `example_bank:everyday-cash` → `https://www.examplebank.example/credit-cards/everyday-cash` (`config/sources/example_bank.yaml`). Fixture: `tests/fixtures/example_bank/card_everyday_cash.html` |
| **Snapshot** | `page_snapshots.snapshot_id = 20261013T035058Z-3c9fc5/89c525a7…1c50` (raw SHA-256 `89c525a7b60b…`, content hash `88b3a095a93d…`). Capture conditions: `capture_context=public_default`, `context_fresh=true`, `cookies_at_start=0`, `locale=en-US`, `timezone_id=America/New_York`, canonical URL with tracking parameters stripped |
| **Classification** | `official_product_detail`. Signals: `product_h1`, `name_in_text`, rate labels (annual fee, APR, foreign transaction, balance transfer), offer markers (`bonus`, `after you spend`), `fee_blocks:1` |
| **Candidate** | `extraction_candidates.id = aee31927-09e3-4e95-8a84-57b4fed4a8ad`, parser `example_bank/1.0.0`, status `valid`, confidence 0.90 (internal only) |
| **Validation** | `R-NAME`, `R-DOMAIN`, `R-PAGE`, `R-DETAIL`, `R-REQ`, `C-INTRO-APR`, `C-FEE`, `C-APR` ×2, `C-CAT>=BASE`, `F-FRESH`, `R-CONFIDENCE`: all pass |
| **Provenance** (examples) | `annual_fee_cents` ← span "$0"; `purchase_apr_min_pct` ← "0% intro APR for 15 months, then 19.24% - 28.24% Variable"; `foreign_tx_fee_pct` ← "3% of each transaction in U.S. dollars"; `offer` ← "Earn a $200 bonus after you spend $500 on purchases in the first 3 months from account opening." Each span is tied to the snapshot above and parser `example_bank/1.0.0` |
| **Canonical product** | `prod.products.id = 1011d520-a9b5-495c-9d87-523ae33b8434`, key `example_bank:credit_card:consumer:example bank everyday cash:-`, version 1 (`initial`) |
| **Current offer** | `prod.offers.id = 82ed3466-d2fb-4d42-a94b-c5b266c86084`: `card_welcome`, `amount_qualifier=exact`, 20000¢, requirement spend 50000¢ in 90 days, `audience=public`, `status=current` |
| **API** | `GET /api/v1/products/1011d520-…` → `label=verified`, `details.annual_fee_cents=0`, `offers[0].state=current` (evaluated at request time) |
| **UI** | `/products/1011d520-…` shows the Verified badge, "Checked …", key facts, the offer with verbatim text and source link, and change history. E2E: `web/e2e/flows.spec.ts` |
| **Recommendation** | `POST /api/v1/recommend` (cash-back goal, groceries $400, dining $200, other $800/month, max fee $0) → **rank 1**, score 91.43, ongoing $264/yr, promotional $200, first-year $464. "Requirement achievable: yes — your estimated $1,400/month × 3 months = $4,200 meets the $500 requirement." |

UUIDs differ on every fresh run. Re-run the commands above to reproduce.

## Pending real-bank traces

| Bank | Status |
|---|---|
| Bank of America | pending: `ENV_NETWORK_BLOCKED` |
| Chase | pending: `ENV_NETWORK_BLOCKED` |
| Capital One | pending: `ENV_NETWORK_BLOCKED` |
| U.S. Bank | pending: `ENV_NETWORK_BLOCKED` |
| American Express | pending: `ENV_NETWORK_BLOCKED` |
