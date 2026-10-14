# Spot check, round 2: 10 Verified cards

Generated 2026-10-14 16:45 UTC from the `prod` schema (exactly what the API serves), after the stricter Verified rules of DESIGN §24.16. None of these cards was in round 1 (see `docs/SPOT_CHECK_TRIAGE.md`).

How to read a row:
- **Earn rates** lists every stored rate, including issuer-portal-only rates, with caps; `other` is the base rate.
- **Welcome bonus** names the official page the offer came from and the capture date. Offers can differ by entry point (online / branch / targeted); compare against that page. A tiered offer lists each tier; non-spend tiers are never counted in recommendations, and "up_to" amounts count $0.
- **Intro APR** keeps the unit the page states (months / billing cycles).
- **Captured** is when the page was fetched; a value that differs on the live page today may be a page change.

| # | Bank | Product | Annual fee | Earn rates (all) | Welcome bonus | Purchase APR | FX fee | Source | Captured |
|---|---|---|---|---|---|---|---|---|---|
| 1 | chase | Chase Sapphire Reserve® Credit Card | $795 | 8x travel (issuer travel portal only)<br>4x airline<br>4x hotel<br>3x dining<br>1x other | exact: 100,000 points after $6,000 spend in 90 days. Offer shown on creditcards.chase.com/rewards-credit-cards/sapphire/reserve as of 2026-10-13 | 19.74%–28.24% | 0% | <https://creditcards.chase.com/rewards-credit-cards/sapphire/reserve> | 2026-10-14 |
| 2 | chase | IHG One Rewards Credit Card | $0 | 3x gas<br>3x dining<br>3x groceries<br>2x other | exact: 125,000 points after $2,000 spend in 90 days. Offer shown on creditcards.chase.com/travel-credit-cards/ihg-rewards-club/one-rewards as of 2026-10-13 | 19.49%–27.99% | 0% | <https://creditcards.chase.com/travel-credit-cards/ihg-rewards-club/one-rewards> | 2026-10-14 |
| 3 | capital_one | VentureOne Business | $0 | 5x hotel (issuer travel portal only)<br>5x travel (issuer travel portal only)<br>1.5x other | exact: 50,000 miles after $4,500 spend in 90 days. Offer shown on www.capitalone.com/small-business/credit-cards/ventureone-business/ as of 2026-10-13 | 16.99%–22.99% | see issuer | <https://www.capitalone.com/small-business/credit-cards/ventureone-business/> | 2026-10-14 |
| 4 | capital_one | Quicksilver Rewards for Students | $0 | 1.5% other | exact: $50 after $100 spend in 90 days. Offer shown on www.capitalone.com/credit-cards/quicksilver-student/ as of 2026-10-13 | 18.74%–28.74% | 0% | <https://www.capitalone.com/credit-cards/quicksilver-student/> | 2026-10-14 |
| 5 | capital_one | Venture X Business | $395 | 2x other | exact: 150,000 miles after $30,000 spend in 90 days. Offer shown on www.capitalone.com/small-business/credit-cards/venture-x-business/ as of 2026-10-13 | see issuer | see issuer | <https://www.capitalone.com/small-business/credit-cards/venture-x-business/> | 2026-10-14 |
| 6 | bank_of_america | Bank of America® Travel Rewards Credit Card | $0 | 1.5x other | exact: 25,000 points after $1,000 spend in 90 days. Offer shown on www.bankofamerica.com/credit-cards/products/travel-rewards-credit-card/ as of 2026-10-13 | 17.74%–27.74%; intro 0% for 15 billing cycles | 0% | <https://www.bankofamerica.com/credit-cards/products/travel-rewards-credit-card/> | 2026-10-14 |
| 7 | bank_of_america | Bank of America® Travel Rewards Credit Card for Students | $0 | 1.5x other | exact: 25,000 points after $1,000 spend in 90 days. Offer shown on www.bankofamerica.com/credit-cards/products/student-rewards-credit-card/ as of 2026-10-13 | 17.74%–27.74%; intro 0% for 15 billing cycles | 0% | <https://www.bankofamerica.com/credit-cards/products/student-rewards-credit-card/> | 2026-10-14 |
| 8 | us_bank | U.S. Bank Altitude® Go Visa Signature® Card | $0 | 4x dining (cap $2,000/quarterly)<br>2x groceries<br>2x gas<br>2x ev_charging<br>2x streaming<br>1x other | exact: 20,000 points after $1,000 spend in 90 days. Offer shown on www.usbank.com/credit-cards/altitude-go-visa-signature-credit-card.html as of 2026-10-13 | 17.74%–27.74%; intro 0% for 15 billing cycles | see issuer | <https://www.usbank.com/credit-cards/altitude-go-visa-signature-credit-card.html> | 2026-10-14 |
| 9 | us_bank | U.S. Bank Altitude® Go Secured Visa® Card | $0 | 4x dining (cap $2,000/quarterly)<br>2x gas<br>2x ev_charging<br>2x streaming<br>2x groceries<br>1x other | No welcome offer on the captured page | see issuer | see issuer | <https://www.usbank.com/credit-cards/altitude-go-secured-visa-credit-card.html> | 2026-10-14 |
| 10 | american_express | Hilton Honors American Express Surpass® Card | $150 ($0 intro) | 12x hotel<br>6x dining<br>6x groceries<br>6x gas<br>4x online_shopping<br>3x other | Check American Express for the current welcome offer | see issuer | see issuer | <https://www.americanexpress.com/us/credit-cards/card/hilton-honors-surpass/> | 2026-10-14 |

Verified cards available per bank after excluding round 1: chase 4, capital_one 8, bank_of_america 5, us_bank 2, american_express 1.

Checked by: ________  Date: ________  Mismatches: ________
