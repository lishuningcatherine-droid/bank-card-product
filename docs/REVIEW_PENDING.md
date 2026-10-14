# Held changes awaiting review

Generated 2026-10-14 21:45 UTC from the open `major_change` review items (7 products: 3 LOW risk, 4 HIGH risk). Prod keeps the previous values for these cards (shown Partially verified) until the item is approved or rejected with `bankrec review approve|reject <id>`. A product's changes are decided together.

**LOW risk**: every change only adds rates or qualifiers that the page states, drops 'travel' read from a
portal's name, or fills a previously empty field; nothing is removed or re-valued. **HIGH risk**: a value is
removed or changed, or an offer appears / changes / disappears.

## HIGH risk (decide one by one)

| Review id | Card | Field | Old → new | Evidence | URL | Recommendation |
|---|---|---|---|---|---|---|
| 357 | Disney® Inspire Visa® Card (chase) | reward_currency | cashback → restricted | new: «Disney Rewards Dollars» | <https://creditcards.chase.com/rewards-credit-cards/disney/inspire> | approve: store currency, not valued (DESIGN §24.8) |
| 357 | Disney® Inspire Visa® Card (chase) | reward_rates | + 1% other; 10% partner; 3% partner | new: «Earn 1% on all other card purchases» / «Earn 10% on card purchases made directly at DisneyPlus.com, Hulu.com or Stream.ESPN.com.*» / «Earn 3% on card purchases at gas stations and most other U.S. Disney locations» | <https://creditcards.chase.com/rewards-credit-cards/disney/inspire> | approve: adds rates / qualifiers the page states; removes nothing (low-risk part) |
| 357 | Disney® Inspire Visa® Card (chase) | offer:card_welcome | — → exact $200 after $1,000 spend in 3 months | «earn a $200 statement credit after you spend $1,000 on purchases in the first 3 months from account opening.*» | <https://creditcards.chase.com/rewards-credit-cards/disney/inspire> | approve if the page shows this offer (new amounts) |
| 358 | Disney® Premier Visa® Card (chase) | reward_currency | cashback → restricted | new: «Disney Rewards Dollars» | <https://creditcards.chase.com/rewards-credit-cards/disney/premier> | approve: store currency, not valued (DESIGN §24.8) |
| 358 | Disney® Premier Visa® Card (chase) | reward_rates | + 1% other; 2% partner; 5% partner | new: «1% on all other card purchases» / «Earn 2% on card purchases at gas stations and most Disney U.S. locations.*» / «Earn 5% in Disney Rewards Dollars on card purchases made directly at DisneyPlus.com, Hulu.com or Stream.ESPN.com» | <https://creditcards.chase.com/rewards-credit-cards/disney/premier> | approve: adds rates / qualifiers the page states; removes nothing (low-risk part) |
| 358 | Disney® Premier Visa® Card (chase) | offer:card_welcome | — → exact $100 after $500 spend in 3 months | «earn a $100 statement credit after you spend $500 on purchases in the first 3 months from account opening.*» | <https://creditcards.chase.com/rewards-credit-cards/disney/premier> | approve if the page shows this offer (new amounts) |
| 359 | Disney® Visa® Card (chase) | reward_rates | + 1% partner | new: «Earn 1% in Disney Rewards Dollars on all card purchases» | <https://creditcards.chase.com/rewards-credit-cards/disney/rewards> | approve: adds rates / qualifiers the page states; removes nothing (low-risk part) |
| 359 | Disney® Visa® Card (chase) | offer:card_welcome | — → exact $50 after $500 spend in 3 months | «earn a $50 statement credit after you spend $500 on purchases in the first 3 months from account opening.*» | <https://creditcards.chase.com/rewards-credit-cards/disney/rewards> | approve if the page shows this offer (new amounts) |
| 317 | U.S. Bank Shield® Visa® Card (us_bank) | offer_capture | True → — | this capture: not stated (not_applicable); prod: «Earn a $20 annual statement credit for 11 consecutive months of purchases.4» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | reject: value missing from this capture (check the page) |
| 317 | U.S. Bank Shield® Visa® Card (us_bank) | reward_rates | + 4% hotel (portal)<br>− 4% travel (portal) | new: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when you use your card.3» prod: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when yo…» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | approve: drops 'travel' read from the portal's name (DESIGN §24.16) (low-risk part) |

## LOW risk (approve in bulk)

| Review id | Bank | Card | Field | Change | Page |
|---|---|---|---|---|---|
| 356 | chase | Chase Freedom Flex® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/cash-back-credit-cards/freedom/flex> |
| 360 | chase | Aer Lingus Visa Signature® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/travel-credit-cards/avios/aer-lingus> |
| 361 | chase | Iberia Visa Signature® Credit Card | reward_rates | (wording only) | <https://creditcards.chase.com/travel-credit-cards/avios/iberia> |
