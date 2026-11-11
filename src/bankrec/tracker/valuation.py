"""What a campaign's reward is worth in dollars, conservatively (DESIGN §27.6).

Cash and statement credits count at face value. Points and miles count only at a floor value an official page
states for cash or statement-credit redemption, or at the value the visitor enters; with neither, the reward is shown
as a number of points with no dollar figure. Every dollar figure says which assumption it rests on.
"""

from __future__ import annotations

from typing import Any

from bankrec.tracker import config


def assumption_text(cents: float, basis: str) -> str:
    return f"Counted at 1 point = ${cents / 100:.4f}".rstrip("0").rstrip(".") + f" ({basis})"


def guaranteed_amount(terms: dict[str, Any]) -> int | None:
    """The amount an applicant is sure to get. A variable offer ("as high as" / "up to") counts only at a minimum the
    issuer publishes (``guaranteed_min``); "starting at N" publishes N as its minimum; an exact offer is its amount."""
    amount = terms.get("total_amount")
    q = terms.get("amount_qualifier")
    if amount is None:
        return None
    if q == "up_to":
        gm = terms.get("guaranteed_min")
        return int(gm) if gm is not None else None
    return int(amount)


def is_variable(terms: dict[str, Any]) -> bool:
    return terms.get("amount_qualifier") in ("up_to", "starting_at")


def value(
    terms: dict[str, Any], program: str | None, overrides: dict[str, float] | None = None
) -> dict[str, Any]:
    out = _value(terms, program, overrides)
    q = terms.get("amount_qualifier")
    if q in ("up_to", "starting_at") and terms.get("total_amount") is not None:
        word = "up to" if q == "up_to" else "starting at"
        top = f"{int(terms['total_amount']):,}"
        if guaranteed_amount(terms) is None:
            out.update(
                cents=None,
                cents_per_point=None,
                depends_on_points_value=terms.get("unit") in ("points", "miles"),
                assumption=f"No dollar value: the offer amount varies by applicant ({word} {top});"
                " no guaranteed minimum is published",
            )
        else:
            note = f"Counted at the published minimum of {guaranteed_amount(terms):,} (the offer is {word} {top})"
            out["assumption"] = note + (f"; {out['assumption']}" if out.get("assumption") else "")
    return out


def _value(
    terms: dict[str, Any], program: str | None, overrides: dict[str, float] | None = None
) -> dict[str, Any]:
    unit, amount = terms.get("unit"), guaranteed_amount(terms)
    out: dict[str, Any] = {
        "cents": None,
        "depends_on_points_value": False,
        "assumption": None,
        "cents_per_point": None,
    }
    if amount is None:
        return out
    if unit in ("cash", "statement_credit"):
        out["cents"] = int(amount)
        return out
    if unit not in ("points", "miles"):
        return out
    out["depends_on_points_value"] = True
    user = (overrides or {}).get(program or "")
    if user is not None and user >= 0:
        out.update(
            cents=round(amount * user),
            cents_per_point=user,
            assumption=assumption_text(user, "your own value"),
        )
        return out
    if terms.get("stated_cash_value_cents") is not None and not is_variable(terms):
        out.update(
            cents=int(terms["stated_cash_value_cents"]),
            assumption="Dollar value as stated on the issuer's page",
        )
        return out
    spec = config.programs().get(program or "") or {}
    floor = spec.get("floor_cents")
    if floor is None:
        out["assumption"] = (
            "No dollar value: no official cash-redemption value for these points (enter your own)"
        )
        return out
    out.update(
        cents=round(amount * float(floor)),
        cents_per_point=float(floor),
        assumption=assumption_text(float(floor), f"{spec.get('basis')}"),
    )
    return out


def first_year_net(v: dict[str, Any], terms: dict[str, Any]) -> int | None:
    fee = terms.get("first_year_fee_cents")
    if v.get("cents") is None or fee is None:
        return None
    return int(v["cents"]) - int(fee)
