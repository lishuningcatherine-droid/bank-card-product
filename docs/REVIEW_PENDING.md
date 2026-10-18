# Held changes awaiting review

Generated 2026-10-18 21:55 UTC from the open `major_change` review items (5 products: 1 LOW risk, 4 HIGH risk). Prod keeps the previous values for these cards (shown Partially verified) until the item is approved or rejected with `bankrec review approve|reject <id>`. A product's changes are decided together.

**LOW risk**: every change only adds rates or qualifiers that the page states, drops 'travel' read from a
portal's name, or fills a previously empty field; nothing is removed or re-valued. **HIGH risk**: a value is
removed or changed, or an offer appears / changes / disappears.

## HIGH risk (decide one by one)

| Review id | Card | Field | Old → new | Evidence | URL | Recommendation |
|---|---|---|---|---|---|---|
| 372 | American Express® Gold Card (american_express) | reward_rates | + 1x other; 2x car_rental (portal); 3x airline [booked_direct]<br>qualifier added: 4x groceries cap $25,000/annual [us_only]<br>− 2x travel (portal); 3x airline (portal) | new: «2X POINTS On Prepaid Car Rentals Booked through AmexTravel.com or Amex Travel App™ and cruises booked and paid through AmexTravel.com.‡» / «3X POINTS On Flights Booked through AmexTravel.com or Amex Travel App™ or directly through airlines.‡» / «Earn 1X Membership Rewards® points on all other eligible purchases.‡» prod: «4X POINTS At Restaurants Worldwide, on up to $50K in purchases per calendar year.‡» / «4X POINTS On Groceries At U.S. supermarkets, on up to $25K in purchases per calendar year.‡» | <https://www.americanexpress.com/us/credit-cards/card/gold-card/> | check the removed rates against the page |
| 365 | U.S. Bank Shield® Visa® Card (us_bank) | offer_capture | True → — | this capture: not stated (not_applicable); prod: «Earn a $20 annual statement credit for 11 consecutive months of purchases.4» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | reject: value missing from this capture (check the page) |
| 365 | U.S. Bank Shield® Visa® Card (us_bank) | reward_rates | + 4% airline (portal); 4% car_rental (portal); 4% hotel (portal)<br>− 4% travel (portal) | new: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when you use your card.3» prod: «4% cash back On prepaid air, hotel and car reservations booked directly in the Travel Center when yo…» | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | approve: drops 'travel' read from the portal's name (DESIGN §24.16) (low-risk part) |
| 365 | U.S. Bank Shield® Visa® Card (us_bank) | benefits | [] → [{'name': 'Earn a $20 annual statement credit for 11 consecutive months of purch | this capture: not stated | <https://www.usbank.com/credit-cards/shield-visa-credit-card.html> | check the new value against the page |
| 366 | U.S. Bank Business Altitude® Connect Visa Signature® Card (us_bank) | offer:card_welcome | {"id": "8334e034-6ff1-49fb-b087-6d3c69fe13c4", "offer_type": "card_welcome"} → — | «Earn a $25 statement credit for your business when you hail a ride» | <https://www.usbank.com/business-banking/business-credit-cards/business-altitude-connect-credit-card.html> | reject unless the offer is gone from the page |
| 367 | U.S. BANK BUSINESS SHIELD™ VISA® CARD (us_bank) | reward_rates | + 5% airline (portal) | new: «5% cash back On prepaid air, hotel and car rentals booked directly in the Travel Center when using your card.4» | <https://www.usbank.com/business-banking/business-credit-cards/business-shield-credit-card.html> | approve: adds rates / qualifiers the page states; removes nothing (low-risk part) |
| 367 | U.S. BANK BUSINESS SHIELD™ VISA® CARD (us_bank) | benefits | [] → [{'name': 'Earn a $50 annual statement credit after $5,000 in purchases made thr | this capture: not stated | <https://www.usbank.com/business-banking/business-credit-cards/business-shield-credit-card.html> | check the new value against the page |

## LOW risk (approve in bulk)

| Review id | Bank | Card | Field | Change | Page |
|---|---|---|---|---|---|
| 364 | us_bank | U.S. BANK CASH+® VISA SIGNATURE® CARD | reward_rates | + 5% car_rental (portal) | <https://www.usbank.com/credit-cards/cash-plus-visa-signature-credit-card.html> |
