# Adding a bank

A new bank needs **only** these five things. Do not change other adapters, the schema, the API, the recommender, or the
frontend. The fictional **Example Bank** was added this way (its files are listed in each step).

1. **Bank config**: copy `config/banks/_template.yaml` to `config/banks/<bank_id>.yaml`.
   Set `official_domains` (registrable domains; subdomains match automatically), `product_types` (`offered`,
   `not_offered` or `unknown`, plus an evidence URL), `meaningful_query_params` (usually none), `referral_url_patterns`,
   `boilerplate_phrases` (hidden text that must never count as a block signal), `cfpb_issuer_names`, and
   `discovery.robots_url` / `sitemaps`. Set `test_only: true` for fictional/test banks.
   *Example:* `config/banks/example_bank.yaml`.
2. **Sources config**: `config/sources/<bank_id>.yaml` lists official product-detail / offer-detail / terms URLs with
   `expected_entity` (the official product name). URLs must be canonical (no tracking or referral parameters) and on an
   official domain. The loader rejects anything else. Offer-bearing sources are always rendered in a fresh browser
   context. Optional: `bankrec discover --bank <bank_id>` writes candidates to `<bank_id>.discovered.yaml`
   (never auto-enabled). *Example:* `config/sources/example_bank.yaml`.
3. **Adapter**: copy `src/bankrec/ingest/adapters/_template.py` to `src/bankrec/ingest/adapters/<bank_id>.py` and
   set `bank_id` and `parser_version`. Describe page structure declaratively in `config/banks/<bank_id>.rules.yaml`
   (`name_selector`, `reward_selector`, `credit_selector`, `benefit_selector`, `offer_selector`,
   `offer_footnote_selector`, `offer_tier_selector`, `waiver_selector`, `apy_tier_selector`, `terms_link_selector`,
   `reward_program_pattern`, `co_brands`). Override hooks only for pages the rules cannot describe. Adapters may
   import only shared modules (enforced by `tests/test_adapter_isolation.py`).
   *Example:* `src/bankrec/ingest/adapters/example_bank.py` + `config/banks/example_bank.rules.yaml`.
4. **Fixtures**: verbatim official pages saved to `tests/fixtures/<bank_id>/`, with a `RETRIEVED.txt`
   (URL, timestamp, method) for real banks. Synthetic pages are allowed **only** for the fictional Example Bank.
   *Example:* `tests/fixtures/example_bank/`.
5. **Tests**: `tests/adapters/test_<bank_id>.py` asserting actual extracted values (not just "did not crash").
   Add `docs/adapters/<bank_id>.md` with a *Known limitations* section (required by the isolation test for non-test
   banks). *Example:* `tests/adapters/test_example_bank.py`.

Then run:

```bash
uv run bankrec registry validate --include-test
uv run pytest tests/adapters/test_<bank_id>.py
uv run bankrec ingest --bank <bank_id>          # add --include-test for test_only banks (refused in prod)
```

`test_only` banks are excluded from production: the registry skips them unless `--include-test` is passed, the API hides
them unless `BANKREC_ENV != prod` and `E2E_TEST_DATA=1`, and `bankrec db seed` refuses them without `--include-test`.
