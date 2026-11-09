"""Discover adapter (www.discover.com/credit-cards/... card pages).

Built from verbatim official pages retrieved on 2026-11-09 (``tests/fixtures/discover/RETRIEVED.txt``); pinned by
``tests/adapters/test_discover.py``. See ``docs/adapters/discover.md``.

* Pages are static HTML. The welcome offer is stated twice: a headline ("Earn a $200 bonus statement credit when you
  spend $500 in the first 3 months.") and a numbered footnote with its full terms ("Footnote 9:" ... "Existing or
  previous cardmembers may not be eligible ... in the past 48 months."). The footnote is read as the offer.
* The first-year "Cashback Match" / miles match states no amount; it is not a fixed-amount offer and is not read
  here (the offer tracker records it separately).
* The FAQ's worked example ("So if you earn $50 cash back, we'll give you another $50.") is never an offer.
"""

from __future__ import annotations

import re
from typing import Any

from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter
from bankrec.ingest.common import cards as K
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, Sourced

_OFFER = re.compile(
    r"^Earn an? \$[\d,]+ bonus statement credit when you (?:open .+? and )?spend \$[\d,]+ in the first \d+ months\b",
    re.IGNORECASE,
)
_EARN = re.compile(
    r"^(?:Plus, )?earn (?:unlimited )?\d{1,2}(?:\.\d{1,2})?\s*(?:%|x)\s+(?:cash back|miles)\b", re.IGNORECASE
)


_EVERY = re.compile(r"earn unlimited \d(?:\.\d)?x miles on every purchase you make, every day\.", re.I)


class Adapter(DeclarativeAdapter):
    bank_id = "discover"
    parser_version = "discover/1.0.0"

    def product_name(self, page: ClassifiedPage) -> str | None:
        # The travel page's h1 is the category ("Travel Credit Card"); the curated name is used when stated.
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
            found = [ln for ln in lines if _OFFER.search(ln)]
            # the footnote states the full terms; the headline is kept only when no footnote restates it
            full = [ln for ln in found if len(ln) > 120]
            return full or found[:1]
        if key == "reward":
            out = [ln for ln in lines if _EARN.search(ln)]
            # Miles: the tile names travel and everyday purchases; the FAQ says it plainly ("you'll earn unlimited
            # 1.5x miles on every purchase you make, every day.")
            out += [m.group(0) for ln in lines if (m := _EVERY.search(ln))][:1]
            return out
        if key in ("credit", "benefit", "offer_footnote", "offer_tier"):
            return []
        return super().statements(page, key, fallback)

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        out = super().fees_and_rates(page, ctx)
        doc = page.doc
        assert doc is not None
        # "No annual fee" stated as its own line under the APR box: a labelled fact
        fee = X.first_line(doc, r"^No annual fee\.?$")
        if fee:
            out["annual_fee_cents"] = ctx.field(0, fee, method="label_regex", name="annual_fee")
        apr_line = X.first_line(doc, r"intro APR for \d+ months on purchases.*variable APR after that")
        if apr_line and (rng := K.apr_range(apr_line)) is not None:
            lo, hi, ev = rng
            out["purchase_apr_min_pct"] = ctx.field(lo, ev, method="label_regex")
            out["purchase_apr_max_pct"] = ctx.field(hi, ev, method="label_regex")
            out["purchase_apr_variable"] = ctx.field(True, ev, method="label_regex")
        return out
