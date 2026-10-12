# Bank of America adapter (`ingest/adapters/bank_of_america.py`)

- **Parser version:** `bank_of_america/0.1.0-unverified`
- **Strategy:** the shared declarative extractors (`ingest/common/extract.py`). These are label-anchored pricing tables
  (Schumer box), reward statements, credits, fee waivers, APY tiers, and offer blocks with qualifiers. No bank-specific
  selectors yet (`config/banks/bank_of_america.rules.yaml` does not exist).
- **Bank config:** `config/banks/bank_of_america.yaml` · **Sources:** `config/sources/bank_of_america.yaml` (currently empty).

## Owner pre-survey notes (unverified from the build environment)

Card pages are reported static but carry hidden "temporarily unavailable" boilerplate even when fully loaded. The phrase is listed in boilerplate_phrases and the classifier never treats a phrase alone as a block. robots.txt disallows /deposits/*.pdf; such PDFs are never fetched (manual capture instead).

## Known limitations

- **Built without a verbatim official fixture.** Every Bank of America domain was refused by the build environment's egress
  policy (`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md), so no selector or label has been checked against a real
  page. The tests run this adapter's code only on synthetic Example Bank pages, and `test_verbatim_official_fixtures`
  is skipped as *pending*.
- **No sources are enabled.** The adapter produces nothing in production until confirmed product URLs are added.
- Before enabling: capture 2–3 verbatim pages per product type into `tests/fixtures/bank_of_america/` with `RETRIEVED.txt`,
  write value assertions, and add selectors to `config/banks/bank_of_america.rules.yaml` wherever the shared extractors miss
  fields.
- Segment is derived from the product name ("Business" → business). Co-brand flags use the brand list in
  `config/co_brands.yaml`. Both may need per-bank rules.
