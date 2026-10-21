# Handoff

Last updated: 2026-10-21 (after phase 2, commit b9cd691). Read this first in a new session, then
`CLAUDE.md` and the `docs/DESIGN.md` sections it points to.

Requirements come from `~/Downloads/BUILD_PROMPT_v2.md` (the brief) and the owner's later messages. Where they
conflict, the owner's later decisions (section 2) win.

---

## 1. Current state (prod, 2026-10-21)

Labels as served by the API at request time (Example Bank, the fictional test bank, excluded).

| Bank | Credit cards V / PV | Checking V / PV | Savings V / PV |
|---|---|---|---|
| American Express | 12 / 0 | 1 / 0 | 1 / 0 |
| Bank of America | 19 / 3 | 0 / 0 (3 in review) | 1 / 0 |
| Capital One | 16 / 5 | 1 / 0 | 0 / 0 (1 in review) |
| Chase | 33 / 5 | 2 / 0 | 1 / 0 |
| U.S. Bank | 6 / 5 | 1 / 0 | 1 / 0 |
| **Total** | **86 / 18** | **5 / 0 (3 in review)** | **4 / 0 (1 in review)** |

V = Verified, PV = Partially verified. "In review" records are not served at all.

Still in review, and why:
- Bank of America Advantage SafeBalance / Plus / Relationship Banking (373–375): their only source is the Advantage
  Banking page, classified as a comparison page (three accounts), so R-DETAIL ("comparison-page values need a detail
  page or review") and R-CONFIDENCE fail. The opening deposit no longer matters (§26.2). Owner decision pending.
- Capital One 360 Performance Savings (379): the APY comes only from a robots-disallowed API ("NaN APY").

Home page ranking: 20 cash card offers, 40 points/miles card offers (ranked apart), 2 checking bonuses (Amex
Rewards Checking $300, Chase Total Checking $400), no savings bonus.

Running stack: the local docker containers (`web`, `api`, `db`) still run images about a week old; nothing has been
redeployed. Event logging (`EVENT_LOGGING_ENABLED`) is off.

---

## 2. Decisions and standing rules

### Working rules (owner, standing)
| Rule | Where recorded |
|---|---|
| Never fabricate rates, fees, bonuses, dates, URLs or product names; synthetic fixtures use only "Example Bank" (`examplebank.example`) | `CLAUDE.md` |
| Obey robots.txt and rate limits; no access-control evasion | brief §2; DESIGN §24.5–24.6 |
| Production code never imports `legacy/`; the frontend uses theme tokens only | `CLAUDE.md`, `docs/DESIGN_SYSTEM.md` |
| Commit and push after each step yourself, then watch CI and fix failures before continuing; keep CI green | owner messages only (recorded here) |
| Docker cleanup: remove dangling images and build cache only. **Never remove volumes** — `pgdata` holds the real ingested data | owner messages only (recorded here) |
| Reply to the owner in Chinese; code, comments, docs and commit messages in English | owner message 2026-10-19 (recorded here) |
| Checks: `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format --check src tests migrations`, `uv run mypy`; web via `PATH=~/.local/bin:$PATH corepack pnpm@10.28.0 -C web lint\|typecheck\|test\|build`; after API changes run `uv run bankrec api openapi` and `pnpm -C web gen:api` (CI diffs `docs/openapi.json`) | `CLAUDE.md`, `.github/workflows/ci.yml` |

### Review authority (owner rule 2026-10-20, replaces all earlier temporary rules)
- Claude may approve only a **pure addition backed by page text that passes every check** (quality gate,
  completeness, consistency): `uv run bankrec review auto-approve` (reviewer `claude-auto`, DESIGN §26.1).
- **Any change or removal of an existing value waits for the owner.**
- Every report lists the items auto-approved that round; `docs/AUTO_APPROVED.md` is regenerated for spot checks.
- Records that later validate close their own stale review items (`superseded`, reviewer `pipeline`).
- A duplicate pair approved as distinct is not raised again (DESIGN §24.22).

### Data rules
| Decision | Where recorded |
|---|---|
| "Verified" = no missing key field and not recheck-pending; stricter rules after spot-check round 1 | DESIGN §9, §24.16 |
| Missing values are never inferred. The **minimum opening deposit** is not a Verified requirement: unstated → "Not stated — confirm with the bank"; excluded only when the user's stated opening limit is below a stated minimum | DESIGN §26.2 (owner 2026-10-20) |
| Rate date shown as the bank page states it ("Rate effective 11/24/2025 per bank page") | DESIGN §26.5 |
| Capture gate: the APY section needs a figure; a product with a degraded page is held for the run | DESIGN §26.3 |
| No-rewards cards: only when owner-confirmed and evidence-backed, never from silence | DESIGN §24.15 |
| Foreign transaction fee is a conditional field | DESIGN §24.11 |
| Qualifier conditions, completeness from tiles and program text, no time-unit conversion, `offer_status none_stated`, secured deposits | DESIGN §24.17 |
| Capture quality gate: a degraded capture never proposes a removal (`CAPTURE_DEGRADED`) | DESIGN §24.18 |
| Restricted store currencies (Disney Rewards Dollars) shown as their own currency, valued only for a matching partner; Disney 10% streaming tier | DESIGN §24.19 |
| United tiered offers stored and shown tier by tier; never "80,000 after $3,000" | DESIGN §24.17, migration 0009 |
| Deposit rates captured for **ZIP 90024 (Los Angeles, CA)**, the one documented ZIP | DESIGN §24.20, `config/capture_location.yaml` |
| `media.bac-assets.com` is an official Bank of America domain (rate-sheet PDFs) | DESIGN §24.21 (**owner confirmation still pending**, see section 4) |
| Account and bonus eligibility only in the bank's own words; never forum or unofficial rules; the recommender quotes, never judges | DESIGN §24.22; owner message 2026-10-19 |
| New-account fee waivers kept in the stated unit (statement periods are not months) | DESIGN §24.22 |

### Product and UI rules (owner message 2026-10-19; these override the older brief)
| Decision | Where recorded |
|---|---|
| The front end and public API show **no scores, score percentages or weights**; dollar estimates (first-year, multi-year) with assumptions stay; the methodology page lists factors in words | DESIGN §26.6 |
| The deterministic scoring is the baseline; ML is only a replaceable ranking layer, gated (real consented events, volume, beats baseline, owner approval) | DESIGN §26.8, `config/ranking.yaml` |
| Behaviour logging is **off by default** (operator switch + visitor opt-in), anonymous events only, never answers, delete-my-data and 180-day purge | DESIGN §26.7 |
| Cash offers/cards and points/miles offers/cards are **ranked separately**; points values labelled "estimated, assumes X¢/point"; non-fixed hotel/airline points never in the cash ranking | DESIGN §26.4, §26.9 (owner 2026-10-20) |
| No bank logos or card art until their terms are confirmed; generic placeholders (`PlaceholderArt`) | DESIGN §25 intro; brief §13.1 |
| Manual refresh is admin-only (CLI or a protected back office), never public | DESIGN §25 intro |
| Offer types `public / targeted / referral / preapproved`; only public offers are ranked or recommended; others are shown labelled | DESIGN §25.1 |
| One product can have offers on several official pages; each offer records its pages (`seen_on`) | DESIGN §25.2 |
| Point values used by the rankings are published on the methodology page: default **1.0¢** per point or mile; a program gets its own value (and joins the cash ranking) only with an issuer-published fixed cash value (`fixed_cash_value: true` in `config/point_values.yaml`, currently none). **The owner will supply program values** | DESIGN §25.3, §26.4 |

### Earlier item decisions (for reference)
Rejected: 78, 80, 81, 293, 294, 317. Approved: 83, 267, 287, 288, 296, 303–306, 356, 360, 361, 368–371 (rendered
Amex captures), 388/389 and 401/402 (Bank of America accounts are distinct), 399 (correction), 400 (Amex Rewards
Checking $300 bonus), 365 (U.S. Bank Shield), 366 (Business Altitude Connect), 372 (Amex Gold) — owner 2026-10-20.

---

## 3. In progress / not finished

- **Phase 1 (public home page, offer types, multi-channel offers): done**, accepted by the owner 2026-10-20.
- **Phase 2: done** (2026-10-21, commits 8e9e9bf, 9a22dca, 470c498, b9cd691): no scores/weights anywhere public;
  consented anonymous events (off by default); gated ranking layer with `bankrec ml train|check|approve`; cash and
  points cards ranked apart. Waiting for the owner's review.
- **T-Mobile and REI store currencies** (model like Disney, low priority): blocked — neither card is registered as a
  source. The owner was asked whether to register them.
- **Review backlog** (older items): Bank of America credit-card conflicts, credit-card `needs_review`, offer reviews,
  112 fuzzy duplicate pairs, CFPB `regulator_conflict`/`regulator_match` items. `uv run bankrec review list`.
- **Not redeployed:** the local docker stack runs old images.

---

## 4. Waiting for the owner

1. **Point values per program** (hotel, airline, bank points) with their basis; until then non-fixed points rank
   only among themselves.
2. **Bank of America Advantage Banking checking (373–375):** treat the Advantage Banking page as each account's
   detail page (it carries each account's own fee and waiver block), or keep them in review.
3. **Event logging:** whether and when to set `EVENT_LOGGING_ENABLED=true` in production.
4. **`media.bac-assets.com`** as a Bank of America official domain: confirm.
5. **T-Mobile and REI:** register the two Capital One cards as sources first?
6. **Item 399:** review the correction Claude approved.
7. **Redeploy** the docker stack (never touch volumes).

---

## 5. Next steps

1. Apply the owner's answers above (point values → `config/point_values.yaml`; BoA decision; event logging).
2. Work through the review backlog under the review rules; run `bankrec review auto-approve` after each ingestion
   and list its approvals in the report.
3. Rebuild and redeploy when the owner asks (do not touch volumes).
4. Keep this file current: update it at the end of every phase or major decision.
