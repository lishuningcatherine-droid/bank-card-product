"""Checking engine (brief §11.3): direct-deposit achievability, fee waivers, state filter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bankrec.recommend.common import (
    DISCLAIMER,
    clip,
    completeness,
    components,
    eligible_offers,
    holding_days,
    minmax,
    usd,
    window_months,
    worst_case_requirement,
)
from bankrec.recommend.config import scoring
from bankrec.recommend.models import (
    Achievability,
    CheckingRequest,
    Excluded,
    OfferView,
    ProductView,
    Reason,
    RecommendResponse,
    Result,
    Values,
)


def fee_waived(
    waivers: list[dict[str, Any]] | None, req: CheckingRequest
) -> tuple[bool, str | None, list[str]]:
    """(waived, which condition, conditions we cannot evaluate from broad inputs)."""
    unknown: list[str] = []
    for w in waivers or []:
        k, amt = w.get("kind"), w.get("amount_cents")
        if k in {"direct_deposit_total", "electronic_deposit_total"} and amt is not None:
            if req.has_direct_deposit and req.monthly_direct_deposit * 100 >= amt:
                return True, w.get("text"), unknown
        elif k in {"min_daily_balance", "min_avg_balance"} and amt is not None:
            if req.can_maintain_balance and req.approx_balance * 100 >= amt:
                return True, w.get("text"), unknown
        else:
            unknown.append(str(w.get("text")))
    return False, None, unknown


def bonus(o: OfferView, req: CheckingRequest) -> tuple[int, Achievability, float]:
    """Highest achievable exact amount (explicit tiers count as exact), the explanation, and the margin."""
    months = window_months(o)
    per_month = scoring()["checking"]["assumptions"]["deposits_per_month"]
    if o.requirement_type == "direct_deposit_total":
        if not req.has_direct_deposit:
            return (
                0,
                Achievability(
                    achievable=False,
                    explanation="No: this bonus requires direct deposit, and you "
                    "said you don't have one available.",
                ),
                0.0,
            )
        total = req.monthly_direct_deposit * 100 * months
        count_possible = int(months * per_month)
        tiers = o.tiers or (
            [{"amount": o.amount_max, "requirement_min_cents": worst_case_requirement(o)}]
            if o.amount_qualifier == "exact"
            else []
        )
        best, best_req = 0, None
        for t in sorted(tiers, key=lambda t: t["amount"]):
            need = t.get("requirement_max_cents") or t.get("requirement_min_cents")
            if need is not None and total >= need and (o.required_dd_count or 0) <= count_possible:
                best, best_req = t["amount"], need
        if best_req is None:
            need = min(
                (t.get("requirement_min_cents") or 0 for t in tiers), default=worst_case_requirement(o) or 0
            )
            why = (
                (
                    f"No: {usd(req.monthly_direct_deposit * 100)}/month × {months:g} months = {usd(int(total))}, "
                    f"below the {usd(need)} required."
                )
                if need
                else "No: the requirement could not be confirmed."
            )
            if o.required_dd_count and o.required_dd_count > count_possible:
                why = f"No: {o.required_dd_count} deposits are required within {months:g} months."
            return 0, Achievability(achievable=False, explanation=why), 0.0
        why = (
            f"Yes: {usd(req.monthly_direct_deposit * 100)}/month × {months:g} months = {usd(int(total))} "
            f"meets the {usd(best_req)} required"
            + (f" and {o.required_dd_count} deposits" if o.required_dd_count else "")
            + "."
        )
        return int(best), Achievability(achievable=True, explanation=why), clip(total / best_req - 1)
    return (
        0,
        Achievability(
            achievable=False,
            explanation="The bonus requirement could not be evaluated from "
            "your inputs, so it is not counted.",
        ),
        0.0,
    )


def recommend(
    products: list[ProductView], req: CheckingRequest, now: datetime | None = None
) -> RecommendResponse:
    now = now or datetime.now(UTC)
    cfg = scoring()
    weights = dict(cfg["checking"]["weights"])
    mult = cfg["bonus_importance_multiplier"][req.bonus_importance]
    weights["net_value"] *= mult
    weights["achievability_margin"] *= mult
    rows: list[dict[str, Any]] = []
    excluded: list[Excluded] = []
    for p in products:
        if p.product_type != "checking":
            continue
        d = p.details
        if p.label != "verified":
            excluded.append(Excluded(product_id=p.id, name=p.name, reason="not Verified"))
            continue
        states = d.get("eligible_states")
        if req.state and states and req.state not in states:
            excluded.append(Excluded(product_id=p.id, name=p.name, reason=f"not offered in {req.state}"))
            continue
        monthly = int(d.get("monthly_fee_cents") or 0)
        waived, waiver, unknown = fee_waived(d.get("fee_waivers"), req) if monthly else (True, None, [])
        eff_monthly = 0 if waived else monthly
        if eff_monthly > req.max_monthly_fee * 100:
            excluded.append(
                Excluded(
                    product_id=p.id,
                    name=p.name,
                    reason=f"monthly fee {usd(monthly)} is above your maximum and not waived",
                )
            )
            continue
        offers = eligible_offers(p)
        offer = offers[0] if offers else None
        amount, ach, margin = (0, None, 0.0)
        if offer is not None:
            amount, ach, margin = bonus(offer, req)
        rows.append(
            {
                "p": p,
                "monthly": monthly,
                "eff": eff_monthly,
                "waiver": waiver,
                "unknown": unknown,
                "offer": offer,
                "bonus": amount,
                "ach": ach,
                "margin": margin,
                "net": amount - eff_monthly * 12,
            }
        )
    net_n = minmax([r["net"] for r in rows])
    results = []
    for i, r in enumerate(rows):
        p, o = r["p"], r["offer"]
        access = p.details.get("access_model")
        branch = (
            0.5
            if access is None or req.access_preference == "either"
            else (1.0 if access == req.access_preference or access == "hybrid" else 0.0)
        )
        raw = {
            "net_value": net_n[i],
            "achievability_margin": r["margin"],
            "qualification_time": clip(1 - window_months(o) * 30 / 180) if r["bonus"] else 0.0,
            "holding_requirement": clip(1 - holding_days(o) / 365) if o else 1.0,
            "balance_burden": 1.0
            if r["eff"] == 0 and (r["monthly"] == 0 or "balance" not in (r["waiver"] or ""))
            else 0.5,
            "branch_fit": branch,
            "completeness": completeness(p),
        }
        score, comps = components(raw, weights)
        lim = []
        if not p.details.get("eligible_states"):
            lim.append("State availability is not stated on the source page; confirm with the bank.")
        if o and (o.holding_period_count or o.holding_period_days):
            n, unit = (
                o.holding_period_count or o.holding_period_days,
                (o.holding_period_unit or "days").replace("_", " "),
            )
            lim.append(f"Bonus requires keeping the account open/funded for {n} {unit}.")
        if r["unknown"] and r["eff"]:
            lim.append("You may qualify for a fee waiver we could not check: " + "; ".join(r["unknown"]))
        fee_text = (
            (
                f"{usd(r['monthly'])}/month"
                + (f" — waived for you ({r['waiver']})" if r["waiver"] else " (not waived under your inputs)")
            )
            if r["monthly"]
            else "No monthly fee"
        )
        why = [
            Reason(
                code="net_value",
                text=f"Estimated first-year value of {usd(r['net'])} "
                f"(bonus {usd(r['bonus'])} − fees {usd(r['eff'] * 12)}).",
                params={"cents": r["net"]},
            )
        ]
        if r["waiver"]:
            why.append(Reason(code="fee_waived", text=f"Monthly fee waived: {r['waiver']}."))
        if r["ach"] is not None and r["ach"].achievable:
            why.append(
                Reason(code="achievable", text="You can reach the bonus requirement with your deposits.")
            )
        results.append(
            Result(
                rank=0,
                product=p,
                score=score,
                components=comps,
                values=Values(
                    ongoing_annual_cents=-r["eff"] * 12,
                    promotional_cents=r["bonus"],
                    first_year_cents=r["net"],
                ),
                fee_text=fee_text,
                current_offer=o,
                achievability=r["ach"],
                why=why,
                limitations=lim,
                assumptions=[
                    "Assumes at least one direct deposit per month during the qualification window."
                ],
            )
        )
    results.sort(key=lambda x: (-x.score, -x.values.first_year_cents, x.product.name))
    for n, res in enumerate(results, start=1):
        res.rank = n
    return RecommendResponse(
        product_type="checking", generated_at=now, results=results, excluded=excluded, disclaimer=DISCLAIMER
    )
