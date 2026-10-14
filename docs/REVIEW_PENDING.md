# Held changes awaiting review

Generated 2026-10-14 21:51 UTC from the open `major_change` review items (4 products: 3 LOW risk, 1 HIGH risk). Prod keeps the previous values for these cards (shown Partially verified) until the item is approved or rejected with `bankrec review approve|reject <id>`. A product's changes are decided together.

**LOW risk**: every change only adds rates or qualifiers that the page states, drops 'travel' read from a
portal's name, or fills a previously empty field; nothing is removed or re-valued. **HIGH risk**: a value is
removed or changed, or an offer appears / changes / disappears.

## HIGH risk (decide one by one)

| Review id | Card | Field | Old → new | Evidence | URL | Recommendation |
|---|---|---|---|---|---|---|
| 317 | U.S. Bank Shield® Visa® Card (us_bank) | offer_capture | True → — | this capture: not stated (not_applicable); prod: «Earn a $20 annual statement credit for 11 consecutive months of purchases.4» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | reject: value missing from this capture (check the page) |
| 317 | U.S. Bank Shield® Visa® Card (us_bank) | reward_rates | + 4% hotel (portal)<br>− 4% travel (portal) | new: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when you use your card.3» prod: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when yo…» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | approve: drops 'travel' read from the portal's name (DESIGN §24.16) (low-risk part) |

## LOW risk (approve in bulk)

| Review id | Bank | Card | Field | Change | Page |
|---|---|---|---|---|---|
| 356 | chase | Chase Freedom Flex® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/cash-back-credit-cards/freedom/flex> |
| 360 | chase | Aer Lingus Visa Signature® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/travel-credit-cards/avios/aer-lingus> |
| 361 | chase | Iberia Visa Signature® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/travel-credit-cards/avios/iberia> |
