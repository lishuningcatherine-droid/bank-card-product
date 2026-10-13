# Manual verification needed

Status as of 2026-10-13 (owner's machine). Each run also writes `reports/<run_id>/manual_verification_needed.{md,csv}`.
**No data was substituted for any item below.**

## How to capture a page manually

1. Open the official URL in a normal browser (no login).
2. Save it with the SingleFile extension (or save the PDF) to `data/manual_snapshots/<bank_id>/<slug>.html`.
3. The URL must be in `config/sources/<bank_id>.yaml` (enabled or disabled). The ones below already are.
4. Run `bankrec ingest --manual data/manual_snapshots/<bank_id>/<slug>.html --source-url <url> --captured-at <YYYY-MM-DD>`.

Manual snapshots go through the same classification, parsing and validation, and are labelled `capture_method=manual`.

## Chase

### Pricing & Terms pages (robots-disallowed: `sites.chase.com` → `User-agent: * / Disallow: /`)

These cards are **Partially verified** because their page does not state the foreign transaction fee (it is only on
the Pricing & Terms page). Capturing the P&T page fills it in; it also adds balance-transfer and cash-advance terms.
The sources are registered as disabled `manual_snapshot` entries (`<slug>-pricing-terms`).

| Card | Pricing & Terms URL (linked from the card page) |
|---|---|
| Chase Freedom Unlimited® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC61498.html |
| Chase Freedom Rise® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC65397.html |
| Ink Business Cash® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63827.html |
| Ink Business Unlimited® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63749.html |
| Ink Business Premier® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63834.html |
| Slate® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63300.html |
| Slate Edge® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC64148.html |
| Disney® Premier Visa® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63172.html |
| Disney® Visa® | https://sites.chase.com/services/creatives/pricingandterms.html/content/dam/pricingandterms/LGC63171.html |

The Chase adapter reads a captured P&T page with the generic pricing-table extractor. **No P&T page could be
fetched to test this**, so check the first manual capture with `bankrec review list`.

### Render timeouts (automatic retry next run; capture manually if they persist)

| Card | URL |
|---|---|
| Sapphire Reserve for Business℠ | https://creditcards.chase.com/business-credit-cards/sapphire/reserve |
| Iberia Visa Signature® | https://creditcards.chase.com/travel-credit-cards/avios/iberia |

## Capital One, Bank of America, U.S. Bank, American Express, CFPB

In progress (see `docs/REACHABILITY.md`).
