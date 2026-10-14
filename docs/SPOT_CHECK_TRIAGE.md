# Spot-check round 1 — triage (2026-10-14)

Owner's manual check of the 10 cards in the first `docs/SPOT_CHECK.md`, compared with the published value, its
provenance span, and the stored snapshot it came from. Quotes are verbatim from the snapshot text (⏎ = line break).

**Verdicts:** *parser* = our extraction is wrong or incomplete; *page changed* = the snapshot shows what we
published, the live page now differs; *report* = the value is right but `SPOT_CHECK.md` displayed it misleadingly;
*misread* = the snapshot and the published value agree with each other and contradict the finding.

| # | Card | Finding | Snapshot evidence | Verdict |
|---|---|---|---|---|
| 1 | Chase Sapphire Preferred | Bonus recorded 60,000 | Published: **75,000 points** after $5,000 in 3 months, span «Earn 75,000 points ⏎ after you spend $5,000 in purchases in the first 3 months from account opening». The only "60,000" in the snapshot is «reimbursement up to $60,000 for theft and collision damage» (auto rental coverage). The provenance guard held; nothing was ever stored as 60,000. | misread |
| 1 | Chase Sapphire Preferred | 5x Chase Travel missing | Snapshot: «5x points ⏎ on Chase Travel*». Published rates have travel 2x only: one-rate-per-category dedupe kept the lower 2x "all other travel" and **dropped the 5x portal rate**. | **parser** |
| 1 | Chase Sapphire Preferred | Other categories | Published: dining 3x, gas 3x, EV 3x, streaming 3x, online grocery 3x, other travel 2x, 1x other — all present; SPOT_CHECK showed only the top three. | report |
| 2 | Ink Business Cash | 5% business categories missing | Snapshot: «Earn 5% cash back on the first $25,000 spent in combined purchases at office supply stores and on internet, cable and phone services». "Office supply stores" / "internet, cable and phone" are not in the vocabulary, so the statement produced no rate. | **parser** |
| 3 | Capital One Venture X | Bonus "none recorded" | The static snapshot (2026-10-13 09:31) contains no "75,000" and no "$4,000": the offer is inserted by the page script, which needs the robots-blocked API. "None recorded" was misleading: the offer was **not captured**, not absent. | **parser** (reporting of an uncaptured offer) |
| 3 | Capital One Venture X | Portal/other categories missing | Published: 10x hotels & rental cars, 5x flights & vacation rentals (both portal-only), 2x other. SPOT_CHECK excluded portal rates. | report |
| 4 | Capital One Savor | APR 18.74–28.74 vs 18.49–28.49 | Snapshot 2026-10-13: «18.74% - 28.74% variable APR after that». | page changed (or misread); next run re-captures |
| 4 | Capital One Savor | Categories missing | Published: 3% groceries, dining, entertainment, streaming; 5% portal; 1% other. SPOT_CHECK showed three. | report |
| 5 | BoA (two cards conflated) | "Only 1.5% other; $250 vs $200" | SPOT_CHECK row 5 was **Unlimited Cash Rewards** (1.5% on all purchases; «Online $250 cash rewards bonus after making at least $1,000»; terms page «You will qualify for $250 bonus cash rewards»). **Customized Cash Rewards** is a different card: published $200 («Online $200 cash rewards bonus»), 2% groceries/wholesale clubs capped $2,500 per quarter (combined), 1% other. | misread (two cards) |
| 5 | BoA Customized Cash | Choice category missing | Snapshot: «Earn 3% cash back + 3% first-year cash back bonus in the category of your choice»; «on the first $2,500 in combined purchases each quarter in the choice category». We dropped cardholder-choice categories by design; they must be represented. | **parser** (completeness) |
| 6 | BoA Premium Rewards | Correct | — | ok |
| 7 | U.S. Bank Altitude Connect | Intro "12 months" vs 15 billing cycles | Published 15, span «0% intro APR … for the first 15 billing cycles». SPOT_CHECK printed it as "15 mo": **the unit was converted silently** (billing cycles shown as months). | **parser** (unit) + misread of the count |
| 7 | U.S. Bank Altitude Connect | Categories incomplete | Published: travel 4x; gas & EV 4x capped $1,000/quarter; dining, streaming, groceries 2x; 1x other. SPOT_CHECK showed three. | report |
| 8 | U.S. Bank Triple Cash Business | Bonus "none recorded" | Snapshot: «Get rewarded with a $750 cash back bonus.1» and footnote «$750 cash back will be awarded if eligible Net Purchases totaling $6,000 or more are made … within 180 days from account opening». The headline has no requirement and the requirement is only in the footnote, so no offer was built. | **parser** (offer detection) |
| 8 | U.S. Bank Triple Cash Business | 3% categories incomplete | Snapshot: «3% cash back on eligible purchases at gas and EV charging stations (transactions of $200 or less)*, office supply stores, cell phone service providers, and restaurants». Published gas and dining only: office supply and cell phone are not in the vocabulary. | **parser** |
| 9 | Amex Hilton Honors | Gas 5x and 3x other missing | Published: 7x hotel, 5x dining, 5x groceries, **5x gas**, **3x other** («5X ⏎ Points ⏎ On Gas ⏎ At U.S. gas stations.» / «3X ⏎ Points ⏎ For Each Dollar ⏎ Spent on other eligible purchases»). SPOT_CHECK showed three. | report |
| 9 | Amex Hilton Honors | 100,000 + $100 offer ends 2026-07-29 | Static snapshot has no "100,000" and no end date: no offer stored, nothing shown as current. Correctly not current (2026-07-29 is past), but "none recorded" must say "not captured". | ok (data) / report |
| 10 | Amex Marriott Brilliant | 2x other missing | Published: **2x other** («2X Points For Each Dollar Spent on other eligible purchases»), 6x hotel, 3x dining, 3x flights. SPOT_CHECK showed three. | report |
| 10 | Amex Marriott Brilliant | Tiered bonus | Not in the static snapshot (script-only). Tiered offers must be representable when captured. | **parser** (schema) |

**Systemic causes found:** (1) one-rate-per-category dedupe dropped portal rates; (2) vocabulary gaps for business
categories; (3) cardholder-choice and partner-merchant rates were dropped instead of represented; (4) an offer whose
requirement sits in a footnote was not built, and an uncaptured offer was reported as "none recorded"; (5) intro
periods in billing cycles were displayed as months; (6) SPOT_CHECK showed only three non-portal rates per card, which
made complete records look incomplete. All are addressed in DESIGN §24.16.
