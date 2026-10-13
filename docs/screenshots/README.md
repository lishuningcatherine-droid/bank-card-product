# Screenshots (test data)

Captured on 2026-10-13 by `SCREENSHOTS=1 pnpm -C web exec playwright test screenshots` at **375px** (mobile) and
**1280px** (desktop). Every product shown belongs to the **fictional Example Bank** (test data banner at the top). No
real bank data could be retrieved from the build environment (docs/REACHABILITY.md).

| File | Page |
|---|---|
| `home-*.png` | Home: the three steps, then browse by type |
| `credit-cards-*.png`, `checking-accounts-*.png`, `savings-accounts-*.png` | Listings with filter bar, product cards, verification badges, offer chips ("Up to" with info button), "Checked …" |
| `product-detail-*.png` | Product detail: key facts, current offer with verbatim text and source, rewards, benefits, change history |
| `recommend-start-*.png`, `quiz-credit-card-*.png` | Quiz: product type first, then type-specific questions |
| `results-credit-card-*.png` | Card results: value split, multi-year view, break-even, "Possible welcome offer: up to …", achievability, score breakdown, point-value adjuster, credit checkboxes |
| `results-checking-*.png` | Checking results with the "Requirement achievable" test |
| `results-savings-*.png` | Savings results with the deposit and holding-period rules |
| `compare-*.png` | Side-by-side comparison (3 cards) |
| `methodology-*.png`, `sources-*.png`, `about-*.png`, `privacy-*.png` | Information pages |
| `empty-state-*.png`, `not-found-*.png` | Empty state and 404 |
