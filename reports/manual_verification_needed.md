# Manual verification needed

Generated from the reachability survey of 2026-10-12 (docs/REACHABILITY.md). Each run also writes
`reports/<run_id>/manual_verification_needed.{md,csv}`.
**No data was substituted for any item below.**

| Bank | What | Reason | What to do |
|---|---|---|---|
| American Express | robots.txt, sitemap, all product pages | `ENV_NETWORK_BLOCKED` (build environment egress proxy, HTTP 403 on CONNECT) | Re-run `bankrec survey` from a session where the allowed domains apply, or locally. Then confirm product URLs. If blocked, use manual capture (below). |
| Bank of America | robots.txt, sitemap, all product pages | `ENV_NETWORK_BLOCKED` | same |
| Capital One | robots.txt, sitemap, all product pages | `ENV_NETWORK_BLOCKED` | same |
| Chase | robots.txt (www + creditcards), sitemaps, all product pages | `ENV_NETWORK_BLOCKED` | same |
| U.S. Bank | robots.txt, all product pages | `ENV_NETWORK_BLOCKED` | same |
| CFPB | TCCP release file, Credit Card Agreements database | `ENV_NETWORK_BLOCKED`; dataset URLs not confirmed | Confirm the dataset URLs, then add `regulator_dataset` sources. Check `config/regulators/cfpb_tccp.yaml` against the release's data dictionary. |

## Manual capture (any blocked, robots-disallowed, or unrenderable source)

1. Open the official URL in a normal browser (no login).
2. Save it with the SingleFile extension (or save the PDF) to `data/manual_snapshots/<bank_id>/<slug>.html`.
3. Add the URL to `config/sources/<bank_id>.yaml` if it is not there yet.
4. Run `bankrec ingest --manual data/manual_snapshots/<bank_id>/<slug>.html --source-url <url> --captured-at <YYYY-MM-DD>`.

Manual snapshots go through the same classification, parsing, and validation, and are labeled `capture_method=manual`.
