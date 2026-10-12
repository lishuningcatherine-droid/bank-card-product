# legacy/ — archived v1 material (read-only, untrusted)

This directory holds code and data from the v1 system. **It is currently empty.** When the v2 rebuild started
(2026-10-12), the repository had no commits and none of the v1 files listed in the build brief existed
(see `docs/AUDIT.md`).

If v1 files turn up later, put them here unchanged:

- `legacy/data/` — v1 CSVs (`sources.csv`, `cards*.csv`, review queues, and so on)
- `legacy/src/` — v1 scraper, parser, recommender, and frontend code

Rules:

1. **Read-only.** Do not edit or "fix" files here. Corrections belong in the v2 pipeline.
2. **Hints only.** Legacy rows may be used only as hints for source discovery, such as a candidate URL or a
   product name to look up on an official page. They must never be loaded into staging or production tables.
3. **No imports.** Production code (`src/bankrec/`, `web/`) must not import from `legacy/`.
   `tests/test_legacy_import_guard.py` enforces this.
