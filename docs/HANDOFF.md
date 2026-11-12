# Handoff

Last updated: 2026-11-11, end of session (offer tracker phases 1–3 plus the owner's reviews of 2026-11-10 and
2026-11-11). Read this first in a new session, then `CLAUDE.md` and the `docs/DESIGN.md` sections it points to
(the offer tracker is DESIGN §27, decisions §27.11–27.13).

Requirements: `~/Downloads/BUILD_PROMPT_v2.md` (original brief), the offer-tracker brief of 2026-11-09 (current
offers + offer history + personal application advice), and the owner's later messages. Where they conflict, the
owner's later decisions win (sections 2 and 3).

Reply to the owner in Chinese; code, comments, docs and commit messages in English. Commit and push after each
step, then watch CI and fix failures before continuing.

---

## 1. Current state

### Offer tracker (local database, 2026-11-11)
- **25 tracked cards, 7 issuers** (Chase, American Express, Citi, Capital One, Bank of America, Discover, Wells
  Fargo), personal and business, **5 starter cards** (Discover it Student Cash Back, Capital One Savor / Quicksilver
  for Students, Platinum Secured, Quicksilver Secured). `config/tracker/cards.yaml`.
- **Campaigns:** 14 active (13 official, 1 manual = Amex Gold), 5 stale and 1 needs-verification (official pages
  not re-confirmed recently: BofA Customized Cash and Premium Rewards, Capital One Savor/Quicksilver for Students,
  Chase Freedom Unlimited; Amex Blue Cash Preferred), 2 expired third-party history records (Sapphire Reserve 125k
  and 150k, *not officially verified*). One current campaign per offer.
- **All 7 manual entries approved by the owner (Catherine, 2026-11-11).** Savor, Venture, Sapphire Preferred and
  Reserve were folded into their existing official campaigns (Savor: verification; Venture: v2 adds the $300 stays
  credit; both Sapphires: v2 adds the eligibility wording; v1 kept). These four rest on a manual check of pages read
  2026-11-10 (the adapters no longer read them); without a new successful check they turn "data out of date" after
  7 days — expected. Evidence: `docs/review/2026-11-11-pending-offers.md`.
- **Rules:** 20 (15 official page-captured, 1 official quoted by a third party = Amex once per lifetime, 1 strong
  community = Chase 5/24, 3 weak community = BofA 2/3/4 and two Capital One rules). `config/tracker/rules.yaml`.
- **Pages / API:** `/` and `/offers` (current offers, no profile needed), `/offers/[id]` (terms, ET deadline, versions,
  status log, checks, rules), product pages (offer history), `/rules`, `/offers/match` (personal check; answers stay
  in the browser). API: `/api/v1/campaigns`, `/campaigns/{id}`, `/campaigns/match`, `/products/{id}/campaigns`,
  `/rules`, `/point-values`, `/tracked-cards`.
- **CLI:** `bankrec offers update|sync|match|evidence|add|amend|pending|approve|reject|set-status|merge-duplicates|
  verify-rules`; `bankrec db check-target` (describes the database without printing its address).
- **Not running automatically.** The worker container and the GitHub schedule are off; the cloud database is not set
  up (section 4). Updates happen only when someone runs `bankrec offers update`.
- **Tests:** Python 511, web unit 107, e2e 36 (CI green). Local e2e needs `psql` (or a shim to the db container) and
  `pnpm exec playwright install chromium`.

### Product catalogue (unchanged since 2026-10-21)
Credit cards 86 Verified / 18 partially verified, checking 5 V (3 in review), savings 4 V (1 in review) across Amex,
BofA, Capital One, Chase, U.S. Bank. Still in review: BofA Advantage SafeBalance / Plus / Relationship (373–375,
comparison page only), Capital One 360 Performance Savings (379, APY only from a robots-disallowed API). The local
docker stack (`web`, `api`) runs old images; nothing has been redeployed. Event logging is off.

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

## 3. Offer tracker: rules decided with the owner (keep them)

| Rule | Where |
|---|---|
| Cards (long-term facts) and campaigns (an offer in a period) are separate; a card can have several campaigns at once and over time | DESIGN §27.1–27.2 |
| Identity = card + channel + offer type + reward structure; only a **material** change makes a new version (amount, unit, tiers, spend, window and its start, fees, start/end, eligibility, channel, restricted components); old versions are kept. Tier terms compare amount/unit/spend/window/incremental only. **Repeated syncs are idempotent** (tested) | §27.2, §27.12 |
| Deadlines in ET; a time only when stated (never filled in as 23:59); countdown only with date + time + zone; "first seen" is never a start date; the application deadline is separate from the spending window | §27.3 |
| Status: active / ending soon (≤ 14 days, confirmed deadline) / expired / withdrawn / needs verification / data out of date (3 failed checks or 7 days). A failed fetch never ends an offer; only a passed confirmed deadline or a reviewer does. Every change logged (auto/manual) | §27.3 |
| History labels: median of this site's records over 24 months; comparisons need ≥ 3 records over ≥ 12 months; "in the history recorded on this site"; third-party records labelled and excludable. **Consecutive versions count as one record only when amount, spend requirement and spend window are all unchanged** | §27.5, §27.13 |
| Values: cash at face value; points only at an official cash value or the visitor's own value; else points only. **Variable ("as high as") offers: only a published guaranteed minimum is used, else points units only and never a "highest" label** (Amex Gold has none) | §27.6, §27.12 |
| **Restricted components** (e.g. Venture's $300 Capital One Travel stays credit, first cardholder year): shown apart, never cash, never converted to miles, not in net value; "no spending requirement stated" when its sentence names none. How/when it is credited is not stated on the readable page — nothing recorded about it | §27.12–27.13 |
| Rule sources: official (page-captured) / official quoted by a third party → **"Needs verification"**, never a conflict, until the issuer's document confirms it / community with **confidence strong** (met → "not a fit for now") or **weak** (met → "confirm first"); every community result says "community-reported rule" | §27.11–27.12 |
| **Chase Sapphire:** approval blocked only while this same card is open; bonus once per card (lifetime). Holding Sapphire Preferred does not affect the Reserve. No family, "one Sapphire at a time" or 48-month rule. The Offer Details "one open" wording is read as this card (kept as a note) | §27.13 |
| Boundary month (an answer exactly N months back for an N-month rule) → "Needs checking", never clear | §27.11 |
| Personal check: six separate judgements, no combined score; approval and bonus eligibility apart; no approval odds; a score never decides alone (FICO ranges only as a signal); missing answers → "needs information", never assumed; reach = natural spend × window ≥ requirement × 1.2, no manufactured spending; income optional (range only); starter cards: short history is a caution, never "approval is easy" | §27.10–27.11 |
| Profile never stored server-side (browser sessionStorage; localStorage only on "remember"); never SSN/EIN/card numbers/logins | §27.10 |
| Manual entries: recorded with who/source/when, **pending until a different person approves (Claude never approves)**; corrections with `offers amend` (history kept); approving an entry for an offer already tracked verifies it (a manual check, or a new version) instead of duplicating | §27.8, §27.12–27.13 |
| Never invent amounts, dates or terms. Third-party history only with verbatim, dated sources; inferred dates labelled as inferred | CLAUDE.md, §27.13 |
| Unreadable pages (robots, JS-only, cookies) → manual entry, not repeated retries: Wells Fargo business cards, Amex application terms, Chase Pricing & Terms, Capital One card API, Venture X offer, Discover first-year match | `config/tracker/cards.yaml` `manual_only` |
| Secrets: connection strings only in environment variables / GitHub secrets, never printed, committed or reported; backups in `backups/` (git-ignored) | §27.12, `docs/NEON_MIGRATION.md` |

---

## 4. Waiting for the owner

### 4.1 Cloud database and automatic updates (manual steps; full runbook `docs/NEON_MIGRATION.md`)
Prepared and rehearsed locally; nothing switched. In order — stop at the first failure:
1. Create a Neon project: PostgreSQL 16, US East.
2. Create a test branch (e.g. `migration-test`); copy its **direct** connection string (pooling off, no `-pooler`,
   `sslmode=require`).
3. In your own terminal: `deploy/neon/backup-local.sh`; `read -rs TARGET_DATABASE_URL && export TARGET_DATABASE_URL`;
   `deploy/neon/restore-to-target.sh backups/<new>.dump`; `deploy/neon/verify-target.sh` (must print "target
   verified"); `unset TARGET_DATABASE_URL`.
4. `gh secret set DATABASE_URL_TEST` (test branch, `postgresql+psycopg://…`), `gh secret set BANKREC_CONTACT_EMAIL`
   (an address you choose; it goes into the crawler's User-Agent), `gh workflow run scheduled-ingest.yml -f
   database=test`, `gh run watch`; then `ALLOW_GROWTH=1 deploy/neon/verify-target.sh`.
5. Production branch: repeat step 3 with a fresh backup on the default branch, `gh secret set DATABASE_URL`, one
   watched run with `-f database=production`.
6. (Your choice) point the API at Neon (`DATABASE_URL`, read-only `API_DATABASE_URL` with role `bankrec_api`), redeploy.
7. **Last:** `gh variable set BANKREC_SCHEDULER --body github` (daily 06:15 UTC). Stop: `gh variable delete
   BANKREC_SCHEDULER`. Rollback table in the runbook; the local volume is never touched.

### 4.2 Decisions
1. **Venture X:** its static page shows no new-cardmember offer; provide an official source to enter it by hand, or
   leave it without a campaign.
2. **Discover first-year Cashback Match / Miles match** (no fixed amount): model it as a campaign type, or leave it out.
3. **Amex once-per-lifetime:** stays "Needs verification" until Amex's own terms can be captured (robots-disallowed);
   supply an official document if you have one.
4. Older, still open: point values per program; BofA Advantage Banking accounts 373–375; `EVENT_LOGGING_ENABLED`;
   `media.bac-assets.com` as a BofA domain; T-Mobile / REI cards; review of item 399; redeploying the docker stack
   (never remove volumes).

---

## 5. Next steps
1. Do section 4.1 with the owner; switch the schedule on only after the test branch passes.
2. Re-verify the four manually verified offers (Savor, Venture, Sapphire Preferred / Reserve) within 7 days, or fix
   their adapters (Chase and Capital One pages changed layout on 2026-11-10).
3. Refresh the stale campaigns listed in section 1 (`bankrec offers update`).
4. Review backlog of the product catalogue (`bankrec review list`; auto-approve rule in section 2).
5. Keep this file current at the end of every phase or owner decision.
