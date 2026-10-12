"""Template adapter. Copy to ``ingest/adapters/<bank_id>.py`` and adjust (see docs/ADDING_A_BANK.md).

Most banks need only:
  * ``bank_id`` and ``parser_version`` below, and
  * selectors in ``config/banks/<bank_id>.rules.yaml`` (name_selector, reward_selector, credit_selector,
    benefit_selector, offer_selector, offer_footnote_selector, offer_tier_selector, waiver_selector,
    apy_tier_selector, terms_link_selector, reward_program_pattern, offer_note, offer_absent_note).
Override hooks from :class:`DeclarativeAdapter` only for pages the rules cannot describe.
Adapters may import only ``bankrec.ingest.common``, ``bankrec.parsers``, ``bankrec.normalize``, ``bankrec.model``,
``bankrec.candidate`` and ``bankrec.ingest.adapters.base`` — never another bank's adapter.
"""

from __future__ import annotations

from bankrec.ingest.adapters.base import DeclarativeAdapter


class Adapter(DeclarativeAdapter):
    bank_id = "new_bank"
    parser_version = "new_bank/0.1.0"
