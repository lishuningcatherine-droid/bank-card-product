"""Chase adapter tests.

Real-bank fixtures must be verbatim official pages with RETRIEVED.txt. None exist yet: Chase's domains were refused by
the build environment's egress policy (docs/REACHABILITY.md). The verbatim test is therefore pending; the adapter's
logic is exercised on synthetic Example Bank pages.
"""

from decimal import Decimal

import pytest

from tests.adapters._helpers import FIX, run_adapter, verbatim_fixtures

PENDING = (
    "pending: no verbatim official Chase fixture (ENV_NETWORK_BLOCKED in build env; see docs/REACHABILITY.md)"
)


@pytest.mark.pending_fixture
@pytest.mark.skipif(not verbatim_fixtures("chase"), reason=PENDING)
def test_verbatim_official_fixtures() -> None:  # pragma: no cover - runs once fixtures are captured
    for f in verbatim_fixtures("chase"):
        raise AssertionError(f"write value assertions for {f.name} before enabling sources")


def test_logic_on_synthetic_card() -> None:
    c = run_adapter("chase", FIX / "example_bank" / "card_everyday_cash.html", "everyday-cash")
    assert c.parser_version == "chase/0.1.0-unverified"
    assert c.value("annual_fee_cents") == 0 and c.value("foreign_tx_fee_pct") == Decimal("3")
    assert c.offers and c.offers[0].value is not None and c.offers[0].value.amount_qualifier == "exact"


def test_logic_on_synthetic_placeholders() -> None:
    s = run_adapter("chase", FIX / "example_bank" / "pages" / "savings_static_nan.html", "high-yield")
    assert (
        s.fields["apy_pct"].null_reason is not None
        and s.fields["apy_pct"].null_reason.value == "requires_render"
    )
    c = run_adapter("chase", FIX / "example_bank" / "pages" / "card_bare_dollar_apr.html", "secured")
    assert c.fields["purchase_apr_min_pct"].null_reason.value == "requires_render"  # type: ignore[union-attr]
