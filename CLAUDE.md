# Project notes for coding agents

- Read `docs/DESIGN.md` (architecture and decisions) before changing the pipeline, schema or scoring.
- Frontend work must follow **`docs/DESIGN_SYSTEM.md`**: use only the theme tokens in `web/src/app/globals.css`;
  no hex/rgb colors or default Tailwind palette classes in components (enforced by `web/src/test/design-tokens.test.ts`).
- Never fabricate rates, fees, bonuses, dates, URLs or product names. Synthetic fixtures may use only the fictional
  "Example Bank" (`examplebank.example`).
- Production code (`src/bankrec`, `web/`) must never import from `legacy/`.
- Python: `uv run pytest`, `uv run ruff check src tests`, `uv run mypy`. Web: `pnpm -C web lint|typecheck|test|build`.
