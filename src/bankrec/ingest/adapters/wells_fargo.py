"""Wells Fargo adapter (creditcards.wellsfargo.com consumer card pages).

Built from verbatim official pages retrieved on 2026-11-09 (``tests/fixtures/wells_fargo/RETRIEVED.txt``); pinned
by ``tests/adapters/test_wells_fargo.py``. See ``docs/adapters/wells_fargo.md``.

* Pages are static HTML. Earn rates are tiles: a rate line ("3X") followed by its label ("on restaurants2", the
  trailing digit is a footnote marker).
* The welcome offer is the hero ("Earn 20,000 bonus points" / "when you spend $1,000 in purchases in the first 3
  months"); the footnote with its full terms ("To qualify for the 20,000 bonus rewards points, ...") is the offer's
  evidence when present.
* The marketing-channel notice ("Offers may differ from time to time and depend on the marketing channel ...") and
  the application rules that follow it are eligibility text, never an offer.
* Business card pages (www.wellsfargo.com/biz/business-credit/credit-cards/) are robots-disallowed: not sources.
"""

from __future__ import annotations

import re
from typing import Any

from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter
from bankrec.ingest.common import cards as K
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, Sourced

_FOOT = re.compile(r"^To qualify for the (?:\$[\d,]+ cash rewards bonus|[\d,]+ bonus rewards points), ", re.I)
_HERO = re.compile(r"^Earn (?:an? )?(?:\$[\d,]+ cash rewards bonus|[\d,]+ bonus points)$", re.I)
# "2% cash rewards are earned for every $1 spent in net purchases ..." (Active Cash footnote)
_EARN = re.compile(r"^\d{1,2}(?:\.\d+)?% cash rewards are earned for every \$1 spent in net purchases", re.I)


class Adapter(DeclarativeAdapter):
    bank_id = "wells_fargo"
    parser_version = "wells_fargo/1.0.0"

    def product_name(self, page: ClassifiedPage) -> str | None:
        # The h1 drops the bank name ("Autograph® Card"); the curated full name is used when the page states it.
        expected = page.source.expected_entity
        if page.doc is not None and expected.lower() in X.norm_ws(page.doc.text).lower():
            return expected
        return super().product_name(page)

    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        doc = page.doc
        if doc is None:
            return []
        lines = [ln.strip() for ln in doc.text.split("\n") if ln.strip()]
        if key == "offer":
            out = []
            for i, ln in enumerate(lines[:-1]):
                if _HERO.match(ln) and lines[i + 1].lower().startswith("when you spend"):
                    # "Earn a $100 cash rewards bonus" / "when you spend $500 in purchases in the first 3 months1Plus,
                    # enjoy ..." → the hero sentence up to the footnote marker
                    tail = re.split(r"(?<=months)\d", lines[i + 1])[0]
                    out.append(f"{ln} {tail}")
            return out
        if key == "offer_footnote":
            return [ln.split(" ←back to content")[0] for ln in lines if _FOOT.match(ln)]
        if key == "reward":
            tiles = K.tile_statements(lines)
            if tiles:
                return tiles
            return [m.group(0) for ln in lines if (m := _EARN.match(ln))][:1]
        if key in ("credit", "benefit", "offer_tier"):
            return []
        return super().statements(page, key, fallback)

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        out = super().fees_and_rates(page, ctx)
        doc = page.doc
        assert doc is not None
        fee = X.first_line(doc, r"^\$0 annual fee$")
        if fee:
            out["annual_fee_cents"] = ctx.field(0, fee, method="label_regex", name="annual_fee")
        apr_line = X.first_line(doc, r"intro APR for \d+ months from account opening on purchases")
        if apr_line and (rng := K.apr_range(apr_line)) is not None:
            lo, hi, ev = rng
            out["purchase_apr_min_pct"] = ctx.field(lo, ev, method="label_regex")
            out["purchase_apr_max_pct"] = ctx.field(hi, ev, method="label_regex")
            out["purchase_apr_variable"] = ctx.field(True, ev, method="label_regex")
        ftf = X.first_line(doc, r"^There is a 3% fee for each foreign transaction")
        if ftf:
            from decimal import Decimal

            out["foreign_tx_fee_pct"] = ctx.field(Decimal("3"), ftf.split(". ")[0], method="label_regex")
        return out
