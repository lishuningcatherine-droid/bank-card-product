# Capital One adapter (`ingest/adapters/capital_one.py`)

- **Parser version:** `capital_one/0.1.0-unverified`
- **Strategy:** the shared declarative extractors (`ingest/common/extract.py`). These are label-anchored pricing tables
  (Schumer box), reward statements, credits, fee waivers, APY tiers, and offer blocks with qualifiers. No bank-specific
  selectors yet (`config/banks/capital_one.rules.yaml` does not exist).
- **Bank config:** `config/banks/capital_one.yaml` · **Sources:** `config/sources/capital_one.yaml` (currently empty).

## Owner pre-survey notes (unverified from the build environment)

Card pages are reported static. The savings APY is rendered client-side and shows as NaN in static HTML: the shared placeholder detector records it as missing with reason requires_render, so savings sources must set requires_render: true.

## Known limitations

- **Built without a verbatim official fixture.** Every Capital One domain was refused by the build environment's egress
  policy (`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md), so no selector or label has been checked against a real
  page. The tests run this adapter's code only on synthetic Example Bank pages, and `test_verbatim_official_fixtures`
  is skipped as *pending*.
- **No sources are enabled.** The adapter produces nothing in production until confirmed product URLs are added.
- Before enabling: capture 2–3 verbatim pages per product type into `tests/fixtures/capital_one/` with `RETRIEVED.txt`,
  write value assertions, and add selectors to `config/banks/capital_one.rules.yaml` wherever the shared extractors miss
  fields.
- Segment is derived from the product name ("Business" → business). Co-brand flags use the brand list in
  `config/co_brands.yaml`. Both may need per-bank rules.
