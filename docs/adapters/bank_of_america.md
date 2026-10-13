# Bank of America adapter (`ingest/adapters/bank_of_america.py`)

- **Parser version:** `bank_of_america/1.0.0`
- **Built from:** 22 consumer card pages from `www.bankofamerica.com/credit-cards/spa-assets/sitemap.xml`, fetched and
  rendered on 2026-10-13. Six rendered captures and one static capture are fixtures in `tests/fixtures/bank_of_america/`
  (`RETRIEVED.txt`); `tests/adapters/test_bank_of_america.py` asserts values read by hand off each page.
- **Sources:** `config/sources/bank_of_america.yaml` (22, rendered, `render_ready_selector: .rates-table-body`).

## How it reads a Bank of America card page

| Field | Where |
|---|---|
| Annual fee, standard APR, intro APR, balance-transfer fee | "Interest Rates & Fees Summary": `.rates-table-body .table-cols` blocks (`h3` label + value). "0% for 15 billing cycles" is stored as 15 months; "None" means no intro APR. The balance-transfer fee is the ongoing fee ("the fee for all future balance transfers is 5%"). |
| Foreign transaction fee | A card-detail block saying "no foreign transaction fee(s)" / "without incurring foreign transaction fees" → 0; otherwise missing. |
| Earn rates | Card-detail paragraphs (`.card-details-cc-module .feature-content`) and the rewards tab's "Automatic …" / "Unlimited …" lines, split one clause per rate. The Customized Cash quarterly cap sentence ("on the first $2,500 in combined purchases each quarter … at grocery stores and wholesale clubs") is attached to the rates it names. |
| Welcome offer | A card-detail block titled "…offer…"/"…bonus…" whose text states an amount and "make/spend $X". |
| Secured deposit | "A minimum security deposit of $200 (maximum of $5,000) …". |

## Known limitations

- **The static HTML holds no product details** (only navigation and the visible message "We're sorry, this page is
  temporarily unavailable"); every source is rendered. A render that does not reach the rates table fails as a
  timeout instead of producing an empty product. The static shell extracts nothing and never validates (tested).
- **Foreign transaction fee** is stated only for travel cards; the "View complete list of rates and fees" page
  (`/credit-cards/terms-and-conditions/?campaignid=…`) is empty both statically and after rendering, so 17 cards are
  Partially verified for this field alone or with others.
- The choice category of Customized Cash (3%, 6% in the first year) depends on the cardholder's choice and is not
  stored as a fixed category. "Miles"/"WorldPoints" earn wording on co-brand cards (Air France, Norwegian, Royal ONE)
  is not parsed: no rates, Partially verified.
- Small-business cards (`/smallbusiness/`) and deposit accounts are not surveyed yet.
