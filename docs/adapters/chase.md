# Chase adapter (`ingest/adapters/chase.py`)

- **Parser version:** `chase/1.0.0`
- **Built from:** 42 verbatim card pages retrieved from `creditcards.chase.com` on 2026-10-13 (plain HTTP, robots
  checked, ≥ 3 s per host). Ten of them are kept as fixtures in `tests/fixtures/chase/` (`RETRIEVED.txt`), covering
  every page template seen; `tests/adapters/test_chase.py` asserts the extracted values, read by hand off each page.
- **Rules:** `config/banks/chase.rules.yaml` · **Bank config:** `config/banks/chase.yaml` ·
  **Sources:** `config/sources/chase.yaml` (38 single-card product pages from `creditcards.chase.com/sitemap.xml`).

## How it reads a Chase card page

| Field | Where |
|---|---|
| Scope | `<main>` minus the browse-cards tag cloud, `nav`, `header`, `footer`. The site header repeats filter labels such as "No Annual Fee (15)" and "Visa (35)"; the tag cloud links "No Foreign Transaction Fees" on *every* card page. |
| Name | `h1`, or the card-name title when the `h1` is stylised upper case ("SAPPHIRE RESERVE" → "Sapphire Reserve for Business℠ Credit Card"). `<sup>SM</sup>` renders as ℠. |
| Annual fee, APR | Labelled blocks: an `h2`/`h3` reading "ANNUAL FEE" / "APR" and the paragraph after it; Sapphire template `…__aprfee--fee` / `…__aprfee--apr`. Intro APR from "0% intro APR for N months from account opening on purchases (and balance transfers)". |
| Foreign transaction fee | Only "No foreign transaction fee(s)…" stated in the product content → 0. Otherwise missing (it is stated only on the Pricing & Terms page). |
| Earn rates | Rate-led statements ("3x points on dining", "Earn 3% on…", Sapphire tiles "5x points" + "on Chase Travel"). Multi-rate sentences are split. Co-brand partner earn is mapped to `airline` / `hotel`. |
| Welcome offer | The "NEW CARDMEMBER OFFER" block, only when it reads "Earn <amount> …". A struck-out previous amount is hidden by the shared text renderer. |

## Known limitations

- **Pricing & Terms pages are robots-disallowed.** `sites.chase.com/robots.txt` is `User-agent: * / Disallow: /`.
  Balance-transfer and cash-advance terms, the penalty APR, and the foreign transaction fee of cards that charge one
  are therefore missing. Cards whose page does not say "no foreign transaction fee" stay **Partially verified**
  (Freedom Unlimited, Freedom Rise, Ink Business Cash/Unlimited/Premier, Slate, Slate Edge, Disney Premier, Disney).
  Manual capture of the P&T page fixes this (`reports/manual_verification_needed.md`).
- **Conservative earn rates.** Left out: stacked "total" rates ("9x total miles on United flights", "14X total points
  at Marriott hotels"), "up to" rates, rotating 5% categories without a stated cap, rates whose spend limit is not in
  a parseable form ("on $150K combined spend"), discounts and statement-credit rebates. When one category shows two
  rates, the lower is kept. Cards can therefore show fewer bonus categories than the page; values are never
  overstated.
- **Co-brand rates.** A rate that names the partner ("on Southwest Airlines purchases") counts as `airline`/`hotel`,
  which the recommender does not apply to the broad user categories. Retail partners (Disney, Instacart, DoorDash)
  keep the generic categories stated in the same sentence (e.g. gas stations).
- **Offers.** Gift cards, free night awards, memberships and partner credits are not recorded as welcome offers
  (Disney, Marriott Bonvoy Boundless/Bountiful headline formats, DoorDash, Instacart). "Earn up to …" offers are
  `up_to` and contribute $0; the United offers ("after qualifying activities") have no stated requirement and go to
  review. The generic "Offers may vary depending on where you apply, for example online or in a branch" notice on
  every page describes channel differences and is not attached to the online amount (see DESIGN §24.4).
- **No rewards stated** on Slate and Slate Edge: reward currency and base rate stay missing (Partially verified).
- **Avios cards** (Aer Lingus, British Airways, Iberia) show earn rates only as unlabelled tiles ("3X", "2X");
  they are not read.
- Not sources: the multi-card pages for Amazon, the IHG family and World of Hyatt (personal and business).
- `networkidle` rendering can time out on some pages (two of 38 on 2026-10-13); the next scheduled run retries.
