# Chase adapter (`ingest/adapters/chase.py`)

- **Parser version:** `chase/0.1.0-unverified`
- **Strategy:** the shared declarative extractors (`ingest/common/extract.py`). These are label-anchored pricing tables
  (Schumer box), reward statements, credits, fee waivers, APY tiers, and offer blocks with qualifiers. No bank-specific
  selectors yet (`config/banks/chase.rules.yaml` does not exist).
- **Bank config:** `config/banks/chase.yaml` · **Sources:** `config/sources/chase.yaml` (currently empty).

## Owner pre-survey notes (unverified from the build environment)

Card pages are reported static; creditcards.chase.com robots allows all; www.chase.com disallows education paths and /content/dam/chase-ux/ratesheets/. Checking bonuses live on separate /personal/offers/... pages (source_kind offer_detail, requires_render). Card pricing and terms are on sites.chase.com (terms_page).

## Known limitations

- **Built without a verbatim official fixture.** Every Chase domain was refused by the build environment's egress
  policy (`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md), so no selector or label has been checked against a real
  page. The tests run this adapter's code only on synthetic Example Bank pages, and `test_verbatim_official_fixtures`
  is skipped as *pending*.
- **No sources are enabled.** The adapter produces nothing in production until confirmed product URLs are added.
- Before enabling: capture 2–3 verbatim pages per product type into `tests/fixtures/chase/` with `RETRIEVED.txt`,
  write value assertions, and add selectors to `config/banks/chase.rules.yaml` wherever the shared extractors miss
  fields.
- Segment is derived from the product name ("Business" → business). Co-brand flags use the brand list in
  `config/co_brands.yaml`. Both may need per-bank rules.
