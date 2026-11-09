# Discover adapter (`ingest/adapters/discover.py`)

- **Parser version:** `discover/1.0.0`
- **Built from:** 2 consumer card pages on `www.discover.com/credit-cards/`, fetched on 2026-11-09 (static HTML).
  Fixtures in `tests/fixtures/discover/` (`RETRIEVED.txt`); `tests/adapters/test_discover.py`.
- **Sources:** `config/sources/discover.yaml`.

## How it reads a Discover card page

| Field | Where |
|---|---|
| Name | The registry name when the page states it ("Discover it Miles Credit Card"); the travel page's h1 is the category. |
| Annual fee | "No annual fee" as its own line. |
| APR | "0% intro APR for 15 months on purchases and balance transfers; 18.74% to 28.74% variable APR after that". |
| Earn rates | "Earn 5% cash back on everyday purchases at different places you shop each quarter ... when you activate." (rotating), "Plus, earn 1% cash back on all other purchases.", "earn unlimited 1.5x miles on every purchase you make, every day." |
| Welcome offer | The numbered footnote with the full terms ("Earn a $200 bonus statement credit when you open ... in the past 48 months."), else the headline. |

## Known limitations

- The first-year Cashback Match / miles match states no amount; it is not stored as a fixed-amount offer (the offer
  tracker can record it by manual entry).
- `/products*` is robots-disallowed; never fetched. Discover has no business card pages in the sitemap.
