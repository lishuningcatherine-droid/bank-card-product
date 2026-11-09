# Wells Fargo adapter (`ingest/adapters/wells_fargo.py`)

- **Parser version:** `wells_fargo/1.0.0`
- **Built from:** 2 consumer card pages on `creditcards.wellsfargo.com`, fetched on 2026-11-09 (static HTML).
  Fixtures in `tests/fixtures/wells_fargo/` (`RETRIEVED.txt`); `tests/adapters/test_wells_fargo.py`.
- **Sources:** `config/sources/wells_fargo.yaml`.

## How it reads a Wells Fargo card page

| Field | Where |
|---|---|
| Name | The registry name ("Wells Fargo Active Cash® Card") when stated; the h1 drops "Wells Fargo" (`heading_drops_brand`). |
| Annual fee | "$0 annual fee". |
| APR | "0% intro APR for 12 months from account opening on purchases ... 18.74%, 24.74% or 28.74% variable APR". |
| Earn rates | Tiles ("3X" / "on restaurants2"); Active Cash: "2% cash rewards are earned for every $1 spent in net purchases". |
| Welcome offer | Hero ("Earn 20,000 bonus points" / "when you spend $1,000 in purchases in the first 3 months"), completed by the footnote "To qualify for the ...". |

## Known limitations

- Business card pages (`www.wellsfargo.com/biz/business-credit/credit-cards/`) and card agreements
  (`/credit-cards/documents/`) are robots-disallowed: business card offers can only be entered manually.
- The "Offers may differ from time to time and depend on the marketing channel" notice and the application rules after
  it are eligibility text, never an offer.
