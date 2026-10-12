# U.S. Bank adapter (`ingest/adapters/us_bank.py`)

- **Parser version:** `us_bank/0.1.0-unverified`
- **Strategy:** the shared declarative extractors (`ingest/common/extract.py`). These are label-anchored pricing tables
  (Schumer box), reward statements, credits, fee waivers, APY tiers, and offer blocks with qualifiers. No bank-specific
  selectors yet (`config/banks/us_bank.rules.yaml` does not exist).
- **Bank config:** `config/banks/us_bank.yaml` · **Sources:** `config/sources/us_bank.yaml` (currently empty).

## Owner pre-survey notes (unverified from the build environment)

Card pages reportedly include the name, bonus, earn rates and caps statically; the APR shows as a bare "$" placeholder, recorded as missing with reason requires_render. robots.txt must be read before any crawl; a sitemap is used only if robots.txt lists one.

## Known limitations

- **Built without a verbatim official fixture.** Every U.S. Bank domain was refused by the build environment's egress
  policy (`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md), so no selector or label has been checked against a real
  page. The tests run this adapter's code only on synthetic Example Bank pages, and `test_verbatim_official_fixtures`
  is skipped as *pending*.
- **No sources are enabled.** The adapter produces nothing in production until confirmed product URLs are added.
- Before enabling: capture 2–3 verbatim pages per product type into `tests/fixtures/us_bank/` with `RETRIEVED.txt`,
  write value assertions, and add selectors to `config/banks/us_bank.rules.yaml` wherever the shared extractors miss
  fields.
- Segment is derived from the product name ("Business" → business). Co-brand flags use the brand list in
  `config/co_brands.yaml`. Both may need per-bank rules.
