# Capital One adapter (`ingest/adapters/capital_one.py`)

- **Parser version:** `capital_one/1.0.0`
- **Built from:** 27 verbatim card pages retrieved from `www.capitalone.com` on 2026-10-13 (plain HTTP, robots
  checked, ≥ 3 s per host). Five are kept as fixtures in `tests/fixtures/capital_one/` (`RETRIEVED.txt`), covering the
  consumer showcase template, the promotional-h1 template (Venture) and the small-business template;
  `tests/adapters/test_capital_one.py` asserts values read by hand off each page.
- **Rules:** `config/banks/capital_one.rules.yaml` · **Bank config:** `config/banks/capital_one.yaml` ·
  **Sources:** `config/sources/capital_one.yaml` (22 card pages).

## How it reads a Capital One card page

| Field | Where |
|---|---|
| Name | The `h1`, unless it is a promotion (Venture: "Enjoy a $300 stays credit, plus earn 75K bonus miles") or is not visible; then the "… from Capital One" eyebrow line, then the document title when the page states it. The bank config declares `.eyebrow` as a product heading for the classifier. |
| Annual fee, APR, credit level, security deposit | Showcase pairs: `h3.showcase-headline` + `.showcase-body` ("Annual Fee" / "$395", "Purchase Rate", "Low intro APR", "Credit Level", "Security Deposit"). Small-business pages: lines "$395 annual fee", "24.74% variable APR.", "Enjoy a $0 annual fee for the first year, and then $95 after that.", or the FAQ answer "has an annual fee of $150". |
| Foreign transaction fee | "No foreign transaction fees" in a showcase pair or a line → 0; otherwise missing. |
| Earn rates | Rate headlines with their body ("10X" + "Miles on hotels & rental cars booked through Capital One Travel"), "Unlimited Rewards" bodies, and "Earn/Get unlimited N% / NX …" lines. "…, plus 1% cash back on all other purchases" is split. Rates booked through Capital One (Business) Travel are portal-only. |
| Welcome offer | "Earn a one-time $X cash bonus / N bonus miles … once/when you spend $Y …" stated in the static HTML. |
| Segment | Business when the page is under `/small-business/` (names such as "Spark Cash" do not say "Business"). |

## Known limitations

- **No rendering.** The page script loads card data from `card-apis.capitalone.com`; that host's robots.txt answers
  403, which the fetcher treats as disallow-all (DESIGN §24.5), so the renderer aborts the request and the app shows
  "Page Not Found". Sources are fetched with plain HTTP; offers stated in the static HTML are recorded (DESIGN §24.6).
  An offer shown only by the script is not seen.
- **Quicksilver** states neither its annual fee nor its APR in the static HTML → needs review (manual capture).
- Business cards and Platinum/QuicksilverOne/SavorOne do not state their foreign transaction fee on the page →
  Partially verified. Venture X Business and Spark Cash Plus are pay-in-full cards: no APR stated (correct).
- **Not registered:** Kohl's, Bass Pro Shops and Cabela's pages state nothing usable statically; T-Mobile and REI pay
  rewards in the retailer's own currency (would be mis-valued as cash back); the union-affinity `partner/up/…` pages.
- "for Good Credit" variants are separate products (no welcome bonus or intro APR); the fuzzy-duplicate pairs they
  form with the main cards are in the review queue, never auto-merged.
- Checking and savings (360 Checking, 360 Performance Savings) are offered but not yet ingested.
