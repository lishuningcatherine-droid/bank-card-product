# U.S. Bank adapter (`ingest/adapters/us_bank.py`)

- **Parser version:** `us_bank/1.0.0`
- **Built from:** 11 card pages (8 consumer, 3 business) from `www.usbank.com/site-map.xml`, fetched and rendered on
  2026-10-13. Four rendered captures and one static capture are fixtures in `tests/fixtures/us_bank/` (`RETRIEVED.txt`);
  `tests/adapters/test_us_bank.py` asserts values read by hand off each page.
- **Sources:** `config/sources/us_bank.yaml` (11, rendered).

## How it reads a U.S. Bank card page

Extraction reads the 140 lines after the first `h1` (product content; reviews, FAQs and the footer come later).

| Field | Where |
|---|---|
| Name | `h1`; an all-capitals `h1` ("U.S. BANK CASH+® VISA SIGNATURE® CARD") is replaced by the page's own mixed-case spelling when one exists. |
| Annual fee | "$0 Annual fee", "$0 intro annual fee for the first year, $95 per year thereafter.", or an anchored "enjoy/with/and no (or $0) annual fee" phrase (recorded as `label_regex`, DESIGN §24.9). |
| APR | "a variable APR applies, currently 17.99% - 28.24%"; intro from "0% intro APR on purchases and balance transfers for the first 15 billing cycles" / "After 12 billing cycles". Static "currently $." → missing, `requires_render`. |
| Earn rates | Rate tiles ("5X points" + "on prepaid hotels …") and rate-led lines, one clause and one sentence per rate. "Booked directly in the Travel Center" is portal-only. |
| Welcome offer | "Earn 20,000 bonus points." + "Just spend $1,000 in Net Purchases in the first 90 days.", "Get a $200 bonus" + its requirement line. |

## Known limitations

- Static HTML shows bare "$" placeholders for the annual fee and APR (pre-survey confirmed); sources are rendered.
  The pages never reach network idle; the renderer waits for `load` plus up to 15 s and records which was reached.
- Cash+ 5% and 2% categories are chosen by the cardholder; they are not stored as fixed categories.
- Foreign transaction fees are stated only on Altitude Connect; the other cards are Partially verified.
- Business Leverage redirects to the business card listing and is not a source. Deposit accounts not surveyed yet.
- Several cards have no mixed-case name on the page and keep the all-capitals `h1` (Cash+, Business Shield).
