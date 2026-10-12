# American Express adapter (`ingest/adapters/american_express.py`)

- **Parser version:** `american_express/0.1.0-unverified`
- **Strategy:** shared declarative extractors, plus two hooks for brief §6.7:
  - **Annual fee from the FAQ.** When no pricing label is present, the answer line that follows an
    annual-fee FAQ question is used. That answer is captured as the evidence span.
  - **Welcome offer.** An offer found on the rendered public page is stored with `audience=public`, its verbatim
    text, and the note "Offers may vary; confirm on American Express at application". When no offer is found, no
    offer record is created and the UI shows "Check American Express for the current welcome offer".

## Owner pre-survey notes (unverified from the build environment)

Product pages statically include earn rates, caps, credits, and the annual fee (often only in the FAQ). Welcome offers
are absent from static HTML, so card sources need `requires_render: true`. The card listing page is a JavaScript
shell, so products are discovered via `index-sitemap.xml`. The savings APY slot is blank statically (render). robots.txt
disallows `/*/apply/`. Rates & Fees pages under disallowed paths are never fetched; CFPB agreement data is used only
for cross-checks, and those URLs are listed for manual capture.

## Known limitations

- **Built without a verbatim official fixture** (`ENV_NETWORK_BLOCKED`, docs/REACHABILITY.md). Hooks are tested on
  synthetic Example Bank pages only. `test_verbatim_official_fixtures` is pending.
- No sources are enabled.
- Network is detected from page text. On Amex pages this resolves to "American Express"; verify on real pages.
