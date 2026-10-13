# American Express adapter (`ingest/adapters/american_express.py`)

- **Parser version:** `american_express/1.0.0`
- **Built from:** 15 consumer card pages from `www.americanexpress.com/en-us-sitemap.xml`, fetched and rendered on
  2026-10-13. Three rendered captures are fixtures in `tests/fixtures/american_express/` (`RETRIEVED.txt`);
  `tests/adapters/test_american_express.py` asserts values read by hand off each page.
- **Sources:** `config/sources/american_express.yaml` (13; plain HTTP since 2026-10-13 20:20 UTC, see below).

## How it reads an American Express card page

Extraction reads 90 lines from the product's own hero: the `h1` occurrence followed by "Annual Fee:" (the name also
appears in cross-sell lists, each with its own fee).

| Field | Where |
|---|---|
| Annual fee | "Annual Fee: $0 intro annual fee for the first year, then $95", "Annual Fee: No Annual Fee", "Annual Fee: $895". FAQ-answer fallback kept from the pre-survey design. |
| APR (rendered only) | "Then a variable APR, 19.74% to 28.74%" or "APR: 19.74% to 28.74% variable APR on purchases". "0% intro APR for **up to** 18 months … may be as short as 6 months" → intro duration `ambiguous` (not stored). |
| Earn rates | Four-line tiles: "6%" / "CASH BACK" / "On Groceries" / "On up to $6,000 per year …". Caps read "$50K" and "U.S." inside the cap sentence. Travel-portal rates (AmexTravel.com) are portal-only; "Select Travel" is its own narrow category. |
| Welcome offer (rendered only) | "Earn $300 Cash Back" + "after you spend $3,000 … in the first 6 months". Recorded with the note "Offers may vary; confirm on American Express at application". |
| Network | "American Express", with a page line naming "American Express … Card" as evidence. |

## Known limitations

- **Rendering stopped working on 2026-10-13.** The first rendered run (20:13 UTC) captured 8 of 13 cards; the other
  five renders came back without product content. A second run (20:17 UTC) with `render_ready_selector: h1` timed
  out on all 13: after about 30 rendered loads within an hour, the headless browser got a page with no product
  content. It was not retried in a loop or worked around (no stealth, no other UA). Static HTTP still returns the
  full product HTML, so sources were switched to plain HTTP (`has_offers: false`). Consequences:
  - welcome offers and APRs are not captured; the UI shows "Check American Express for the current welcome offer";
  - the 8 cards first published with rendered offers are now **recheck pending** (their offers "disappeared"):
    excluded from recommendations until `bankrec review` resolves them;
  - to try rendering again later, set `has_offers: true` on the sources (one config change).
- The Gold Card's static `h1` is a promotion and the Platinum Card's static page states no product name: both are
  refused statically (Gold keeps its rendered record, recheck pending).
- Amex EveryDay Preferred and Cash Magnet pages have no product content: not sources. Business cards not surveyed.
- Rates & Fees pages are never fetched; foreign transaction fees appear on the page only for some cards.
