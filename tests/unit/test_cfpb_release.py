"""The CFPB TCCP parser on the real release file (tests/fixtures/cfpb/RETRIEVED.txt). Values read off the workbook."""

from decimal import Decimal
from pathlib import Path

from bankrec.crosscheck.cfpb import parse_tccp

F = Path(__file__).resolve().parents[1] / "fixtures" / "cfpb" / "cfpb_tccp-data_2025-12-31.xlsx"


def test_real_release_parses_with_confirmed_mapping() -> None:
    rows = parse_tccp(F.read_bytes())
    assert len(rows) > 500
    issuers = {r.issuer_name for r in rows}
    assert {"Jpmorgan Chase Bank, National Association", "American Express National Bank"} <= issuers
    [dd] = [r for r in rows if r.plan_name == "DoorDash Rewards Mastercard"]
    # Purchase APR 0.1824 / 0.2774 (fractions), balance-transfer fee 0.05, annual fee blank (not reported → absent)
    assert dd.fields["purchase_apr_min_pct"] == Decimal("18.24") and dd.fields[
        "purchase_apr_max_pct"
    ] == Decimal("27.74")
    assert dd.fields["bt_fee_pct"] == Decimal("5.00") and "annual_fee_cents" not in dd.fields
    [uq] = [r for r in rows if r.plan_name == "United Quest Card"]
    assert uq.fields["annual_fee_cents"] == 35000
