# Manual offer entries (DESIGN §27.8)

Use a manual entry when an offer cannot be read automatically: targeted or pre-approved invitations, branch-only and
referral offers, pages that are robots-disallowed or need JavaScript/cookies, pages whose layout keeps changing, and
third-party records of past offers. Do not retry an unreadable page repeatedly — enter it by hand instead.

1. Write one YAML (or JSON) file per offer, e.g. in `config/tracker/manual_entries/`. Fields
   (`bankrec.tracker.manual.ManualCampaignIn`):
   - `card_key` (from `config/tracker/cards.yaml`), `channel` (`public|targeted|referral|branch`), `offer_type`
   - `tiers`: one per step — `amount`, `unit` (`cash|statement_credit|points|miles|free_night|other`), `unit_name`,
     `spend_cents`, `window_count`, `window_unit`, `window_start` (`account_opening|approval|card_membership|not_stated`),
     `text` (verbatim)
   - `annual_fee_cents`, `first_year_fee_cents`, `eligibility_text` (verbatim)
   - `start` / `end`: `{date, time?, time_zone?, text}` — give a time only if the source states one, with its zone;
     never add 23:59 yourself. Leave out an unknown date.
   - `source_kind` (`official|third_party`), `source_url`, `source_excerpt` (verbatim), `observed_from`
2. `uv run bankrec offers add FILE --by YOUR_NAME` — the entry is stored as **pending review** with who entered it,
   the source and the entry time. It is not shown publicly yet.
3. A different person reviews it against the source: `uv run bankrec offers pending`, then
   `uv run bankrec offers approve ID --reviewer NAME` or `offers reject ID --reviewer NAME --note "…"`.
4. Status changes a reviewer confirms (ended, withdrawn): `uv run bankrec offers set-status CAMPAIGN_ID STATUS
   --reason "…" --reviewer NAME`. They are logged with trigger `manual`.

Third-party entries are labelled "Third-party source (not confirmed by the issuer)" and can be excluded from history
labels. Never enter amounts, dates or terms from memory.
