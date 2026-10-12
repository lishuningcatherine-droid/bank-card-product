"""American Express adapter.

Built WITHOUT a verbatim official fixture (domain refused by the build environment's egress policy; see
docs/REACHABILITY.md). Behaviour follows brief §6.7 and the owner's pre-survey notes:

* static product pages carry earn rates, caps, credits and the annual fee — the fee is often stated only in an FAQ
  answer, so that answer is captured as evidence when no pricing label is present;
* welcome offers appear only on the rendered public page (``requires_render``); when found they get the note
  "Offers may vary; confirm on American Express at application"; when absent no offer record is created and the
  UI says "Check American Express for the current welcome offer";
* Rates & Fees pages under robots-disallowed paths are never fetched (enforced by the fetcher, not here).
"""

from __future__ import annotations

import re

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter
from bankrec.model import ExtractionContext
from bankrec.parsers.money import parse_fee_schedule

OFFER_NOTE = "Offers may vary; confirm on American Express at application"
OFFER_ABSENT = "Check American Express for the current welcome offer"
_FAQ_FEE_Q = re.compile(r"what is the annual fee|is there an annual fee|annual fee for the", re.IGNORECASE)


class Adapter(DeclarativeAdapter):
    bank_id = "american_express"
    parser_version = "american_express/0.1.0-unverified"

    def offer_note(self, page: ClassifiedPage) -> str | None:
        return OFFER_NOTE

    def offer_absent_note(self, page: ClassifiedPage) -> str | None:
        return OFFER_ABSENT

    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        if c.value("annual_fee_cents") is not None:
            return
        lines = page.text.split("\n")
        for i, ln in enumerate(lines):
            if _FAQ_FEE_Q.search(ln) and i + 1 < len(lines):
                answer = lines[i + 1]
                sched = parse_fee_schedule(answer)
                if sched.ongoing_cents is not None:
                    c.fields["annual_fee_cents"] = ctx.field(sched.ongoing_cents, answer, method="label_regex",
                                                             name="annual_fee_faq")
                    c.notes.append("annual fee taken from FAQ answer")
                return
