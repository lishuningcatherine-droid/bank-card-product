# Handoff

Last updated: 2026-10-20 (after commit 7939a22, CI green on all jobs). Read this first in a new session, then
`CLAUDE.md` and the `docs/DESIGN.md` sections it points to.

Requirements come from `~/Downloads/BUILD_PROMPT_v2.md` (the brief) and the owner's later messages. Where they
conflict, the owner's later decisions (section 2) win.

---

## 1. Current state (prod, 2026-10-20)

Labels as served by the API at request time (Example Bank, the fictional test bank, excluded).

| Bank | Credit cards V / PV | Checking V / PV | Savings V / PV |
|---|---|---|---|
| American Express | 11 / 1 | 1 / 0 | 1 / 0 |
| Bank of America | 19 / 3 | 0 / 0 (3 in review) | 0 / 1 |
| Capital One | 16 / 5 | 1 / 0 | 0 / 0 (1 in review) |
| Chase | 33 / 5 | 0 / 0 (2 in review) | 1 / 0 |
| U.S. Bank | 6 / 5 | 1 / 0 | 1 / 0 |
| **Total** | **85 / 19** | **3 / 0 (5 in review)** | **3 / 1 (1 in review)** |

V = Verified, PV = Partially verified. "In review" records are not served at all.

The deposit records still in review, and why:
- Chase Total Checking (397) and Chase Premier Plus Checking (381): no allowed Chase page states the minimum
  opening deposit.
- Bank of America Advantage SafeBalance / Plus / Relationship Banking (373–375): the same; the fee schedule that
  states it is a robots-disallowed PDF.
- Capital One 360 Performance Savings (379): the APY comes only from a robots-disallowed API (the page shows
  "NaN APY").
- Bank of America Advantage Savings is published as Partially verified (opening deposit not stated).

Published offers: 64 current and 1 recheck-pending, all `public`. Home page ranking (DESIGN §25.3) currently ranks
60 card offers (1 more "up to" offer listed unranked) and 1 checking bonus (Amex Rewards Checking $300); no savings
bonus is current. Offers on Partially verified products are shown but not ranked.

Running stack: the local docker containers (`web`, `api`, `db`) still run images about a week old. The code on the
branch is newer; nothing has been redeployed.

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

### Review authority (owner decisions, recorded here)
- The owner decides every HIGH-risk item individually.
- For items the owner cannot see: a **removal caused by a degraded capture → reject**; a **page-evidenced addition →
  approve**; **anything else → ask the owner**.
- A correction to a value we published wrongly may be approved by Claude, but must be disclosed (e.g. item 399,
  the Bank of America $1,000 opening deposit misread from a CD/IRA rate-sheet line, reviewer `claude-correction`).
- Claude approvals under these rules use reviewer `claude-owner-rule` and quote the page in the note.
- A duplicate pair approved as distinct is not raised again (DESIGN §24.22).

### Data rules
| Decision | Where recorded |
|---|---|
| "Verified" = no missing key field and not recheck-pending; stricter rules after spot-check round 1 | DESIGN §9, §24.16 |
| Missing values are never inferred, including the **minimum opening deposit**: if no allowed official page states it, the record stays in review / Partially verified; the owner may supply it with `bankrec review edit` | DESIGN §24.21; owner message 2026-10-18 |
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
| The front end shows **no scores, score percentages or weights**; dollar estimates (first-year, long-term) with their assumptions stay | DESIGN §25 intro. **Not yet applied** to the results page (ScoreBreakdown) and the methodology page (weight table): planned for phase 2 |
| The deterministic scoring stays as the baseline; ML is only a replaceable ranking layer and may not become the default without real labelled data | owner message (recorded here); phase 2 |
| Behaviour logging is **off by default**: only after explicit consent, anonymous events only, never the raw questionnaire inputs, with a way to delete | owner message (recorded here); phase 2 |
| No bank logos or card art until their terms are confirmed; generic placeholders (`PlaceholderArt`) | DESIGN §25 intro; brief §13.1 |
| Manual refresh is admin-only (CLI or a protected back office), never public | DESIGN §25 intro |
| Offer types `public / targeted / referral / preapproved`; only public offers are ranked or recommended; others are shown labelled | DESIGN §25.1 |
| One product can have offers on several official pages; each offer records its pages (`seen_on`) | DESIGN §25.2 |
| Point values used by the home page ranking are published on the methodology page: default **1.0¢** per point or mile; a program gets its own value only from an issuer-published fixed cash value (`config/point_values.yaml`, currently none) | DESIGN §25.3; brief §11 |

### Earlier item decisions (for reference)
Rejected: 78, 80, 81, 293, 294, 317. Approved: 83, 267, 287, 288, 296, 303–306, 356, 360, 361, 368–371 (rendered
Amex captures), 388/389 and 401/402 (Bank of America accounts are distinct), 399 (correction), 400 (Amex Rewards
Checking $300 bonus).

---

## 3. In progress / not finished

- **Phase 1 (public home page, offer types, multi-channel offers): done** — commits 6b8bd71, 7939a22. Waiting
  for the owner's sign-off before phase 2.
- **Phase 2 (not started):** personalised recommendations reworked, the score and weight display removed from
  the front end, opt-in anonymous event logging with deletion, a training interface with the deterministic scorer
  as the baseline.
- **T-Mobile and REI store currencies** (model like Disney, low priority): blocked, because neither card is
  registered as a source (only `config/banks/capital_one.rules.yaml` mentions them). The owner was asked whether to
  register them.
- **Review backlog** (open items, mostly older than the 2026-10-19 work): 16 credit-card conflicts (Bank of
  America 209–226), 12 credit-card `needs_review` (e.g. 24, 77, 79, 201–205, 210, 214, 227, 355), 8 offer reviews,
  112 fuzzy duplicate pairs, 89 CFPB `regulator_conflict` and 24 `regulator_match` items. Use
  `uv run bankrec review list` / `show <id>`; `docs/REVIEW_PENDING.md` was last regenerated before the deposit work.
- **Not redeployed:** the local docker stack runs old images (section 1).

---

## 4. Waiting for the owner

1. **Hotel and airline point values.** With the default 1.0¢, IHG cards rank 2nd–5th on the home page (190,000
   IHG points shown as $1,900). Options: the owner supplies program values with their basis; rank points offers
   separately from cash offers; or keep the default.
2. **Phase 2 go-ahead**, including removing the ScoreBreakdown on results and the weight table on the methodology
   page as part of it.
3. **Card review items 365, 366, 372:**
   - 365, U.S. Bank Shield: the re-proposal the owner specified.
   - 366, U.S. Bank Business Altitude Connect: 75,000 points after $6,000 in 180 days, replacing a misread $25
     ride credit; recommended approve.
   - 372, Amex Gold: adds the 1X base rate and 3X flights (either booking channel), drops misread portal-only rates;
     recommended approve.
4. **Minimum opening deposits** for Chase Total Checking, Chase Premier Plus Checking and the three Bank of America
   Advantage Banking accounts: supply them (`bankrec review edit`) or leave them in review.
5. **`media.bac-assets.com`** as a Bank of America official domain: confirm.
6. **T-Mobile and REI:** register the two Capital One cards as sources first?
7. **Item 399:** review the correction Claude approved.

---

## 5. Next steps

1. After the owner signs off phase 1, start phase 2 in this order:
   - remove scores and weights from the front end;
   - rework personalised recommendations, keeping dollar estimates and their assumptions;
   - add consented, anonymous, deletable event logging (off by default);
   - add the ML ranking interface behind the deterministic baseline (not the default without real labels).
   Stop and report after each part.
2. Apply the owner's point-value decision, if any, to `config/point_values.yaml` and the methodology page.
3. Rebuild and redeploy the docker stack when the owner wants the new home page live (do not touch volumes).
4. Work through the review backlog per the review rules above; regenerate `docs/REVIEW_PENDING.md`.
5. Keep this file current: update it at the end of every phase or major decision.
