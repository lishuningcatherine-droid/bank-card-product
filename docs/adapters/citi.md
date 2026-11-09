# Citi adapter (`ingest/adapters/citi.py`)

- **Parser version:** `citi/1.0.0`
- **Built from:** 3 card pages (2 consumer, 1 business) on `www.citi.com/credit-cards/`, rendered on 2026-11-09. All
  three rendered captures are fixtures in `tests/fixtures/citi/` (`RETRIEVED.txt`); `tests/adapters/test_citi.py`
  asserts values read by hand off each page.
- **Sources:** `config/sources/citi.yaml` (rendered). Registered for the offer tracker (`config/tracker/cards.yaml`).

## How it reads a Citi card page

| Field | Where |
|---|---|
| Name | The registry's official name when the page states it verbatim. |
| Annual fee | The pricing box ("Annual Fee1" / "$95") or the hero ("$99" / "Annual Fee, waived for the first year1"). |
| APR | The "Variable APR" box, only when its next line says it applies to purchases. |
| Earn rates | Tile statements ("10 points per dollar spent on Hotels, Car Rentals and Attractions booked on cititravel.com"); "booked on cititravel.com" is portal-only. AAdvantage lines ("Earn 2 AAdvantage® miles for your business on every $1 spent at ..."). Double Cash: "Unlimited 2% cash back on purchases". |
| Welcome offer | The rendered hero ("Earn 60,000 bonus points" / "after spending $4,000 in the first 3 months"); eligibility from the notice under it, starting at "New account bonus offer is not available" / "Bonus ThankYou® Points are not available". |

## Known limitations

- The static HTML has no numbers; every source is rendered. Card data comes from `aemapi.citi.com` (robots.txt allows
  it, checked 2026-11-09).
- Pages under `*additional-information` (pricing and terms) are robots-disallowed; never fetched.
- Citi Custom Cash: the page says "Citi is no longer accepting applications for the Citi Custom Cash® Card product as
  of May 28, 2026." The source is disabled.
- AAdvantage Business: "telecommunications merchants and cable and satellite providers" maps to no category; the
  card's earn rates are marked incomplete rather than guessed.
- The Double Cash bonus is stated in dollars; the eligibility notice says it is paid as ThankYou® Points.
