"""Chase adapter.

Built from the shared declarative extractors WITHOUT a verbatim official fixture: Chase's domains were refused by
the build environment's egress policy (docs/REACHABILITY.md). Bank-specific behaviour below comes from the owner's
pre-survey notes and is covered by Example-Bank-style synthetic tests only. See docs/adapters/chase.md.
"""

from __future__ import annotations

from bankrec.ingest.adapters.base import DeclarativeAdapter


class Adapter(DeclarativeAdapter):
    bank_id = "chase"
    parser_version = "chase/0.1.0-unverified"
