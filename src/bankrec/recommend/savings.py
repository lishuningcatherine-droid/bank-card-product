"""Savings engine (brief §11.4): tier APY, deposit and holding-period rules, liquidity."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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
)
from bankrec.recommend.common import worst_case_requirement as wcr
from bankrec.recommend.config import scoring
from bankrec.recommend.models import (
    Achievability,
    Excluded,
    ProductView,
    Reason,
    RecommendResponse,
    Result,
    SavingsRequest,
    Values,
)


def deposit_dollars(req: SavingsRequest) -> int:
    lo, hi = scoring()["savings"]["deposit_ranges_dollars"][req.deposit_range]
    return int(lo if hi is None else (lo + hi) / 2)


def tier_apy(d: dict[str, Any], balance_cents: int) -> Decimal | None:
    tiers = d.get("apy_tiers")
    if tiers:
        chosen = None
        for t in sorted(tiers, key=lambda t: t["min_balance_cents"]):
            if balance_cents >= t["min_balance_cents"]:
                chosen = t
        return Decimal(str(chosen["apy_pct"])) if chosen else None
    return Decimal(str(d["apy_pct"])) if d.get("apy_pct") is not None else None


def recommend(
    products: list[ProductView], req: SavingsRequest, now: datetime | None = None
) -> RecommendResponse:
    now = now or datetime.now(UTC)
    cfg = scoring()["savings"]
    m = cfg["apy_vs_bonus_multiplier"][req.apy_vs_bonus]
    weights = dict(cfg["weights"])
    weights["apy"] *= m["apy"]
    weights["bonus"] *= m["bonus"]
    dep = deposit_dollars(req)
    dep_c = dep * 100
    rows: list[dict[str, Any]] = []
    excluded: list[Excluded] = []
    for p in products:
        if p.product_type != "savings":
            continue
        d = p.details
        if p.label != "verified":
            excluded.append(Excluded(product_id=p.id, name=p.name, reason="not Verified"))
            continue
        if req.state and d.get("eligible_states") and req.state not in d["eligible_states"]:
            excluded.append(Excluded(product_id=p.id, name=p.name, reason=f"not offered in {req.state}"))
            continue
        apy = tier_apy(d, dep_c)
        if apy is None:
            excluded.append(Excluded(product_id=p.id, name=p.name, reason="no verified APY for your deposit"))
            continue
        min_open = d.get("min_opening_deposit_cents")
        if min_open is not None and dep_c < min_open:
            excluded.append(
                Excluded(product_id=p.id, name=p.name, reason=f"minimum opening deposit {usd(min_open)}")
            )
            continue
        monthly = int(d.get("monthly_fee_cents") or 0)
        waived = False
        for w in d.get("fee_waivers") or []:
            if (
                w.get("kind") in {"min_daily_balance", "min_avg_balance"}
                and w.get("amount_cents") is not None
                and dep_c >= w["amount_cents"]
            ):
                waived = True
        eff = 0 if waived else monthly
        if eff > req.max_monthly_fee * 100:
            excluded.append(Excluded(product_id=p.id, name=p.name, reason="monthly fee above your maximum"))
            continue
        interest = int(Decimal(dep_c) * apy / 100 * req.holding_months / 12)
        offers = eligible_offers(p)
        o = offers[0] if offers else None
        bonus, ach = 0, None
        if o is not None:
            need = wcr(o)
            hold_days = holding_days(o)
            reasons = []
            if o.requirement_type == "new_money_deposit" and need is not None and dep_c < need:
                reasons.append(
                    f"your deposit (about {usd(dep_c)}) is below the {usd(need)} new-money requirement"
                )
            if o.requirement_type not in {"new_money_deposit", None} or (o.requirement_type and need is None):
                reasons.append("the requirement could not be evaluated from your inputs")
            if hold_days and req.holding_months * 30 < hold_days:
                reasons.append(
                    f"you plan to hold for {req.holding_months} months but the bonus requires "
                    f"{hold_days} days"
                )
            if o.amount_qualifier != "exact":
                reasons.append("the bonus amount is not stated exactly")
            if reasons:
                ach = Achievability(
                    achievable=False, explanation="Bonus not counted: " + "; ".join(reasons) + "."
                )
            else:
                bonus = int(o.amount_max or 0)
                ach = Achievability(
                    achievable=True,
                    explanation=(
                        f"Bonus counted: your deposit (about {usd(dep_c)}) meets the {usd(need or 0)} requirement and "
                        f"your {req.holding_months}-month horizon covers the {hold_days}-day hold."
                    ),
                )
        limit = d.get("max_withdrawals_per_month")
        liq = 1.0
        if req.liquidity_need == "high":
            liq -= 0.4 if limit else 0.0
            liq -= 0.4 if o and holding_days(o) > 90 else 0.0
        elif req.liquidity_need == "medium":
            liq -= 0.2 if limit else 0.0
        rows.append(
            {
                "p": p,
                "apy": apy,
                "interest": interest,
                "bonus": bonus,
                "eff": eff,
                "monthly": monthly,
                "ach": ach,
                "o": o,
                "liq": liq,
                "net": interest + bonus - eff * req.holding_months,
                "waived": waived,
            }
        )
    net_n = minmax([r["net"] for r in rows])
    apy_n = minmax([float(r["apy"]) for r in rows])
    bonus_n = minmax([r["bonus"] for r in rows])
    results = []
    for i, r in enumerate(rows):
        p = r["p"]
        raw = {
            "net_value": net_n[i],
            "apy": apy_n[i],
            "bonus": bonus_n[i],
            "liquidity_fit": clip(r["liq"]),
            "fee_fit": 1.0 if r["eff"] == 0 else 0.3,
            "completeness": completeness(p),
        }
        score, comps = components(raw, weights)
        lim = []
        if p.details.get("max_withdrawals_per_month"):
            lim.append(f"Withdrawal limit: {p.details.get('withdrawal_restrictions')}")
        if not p.details.get("eligible_states"):
            lim.append("State availability is not stated on the source page; confirm with the bank.")
        fee_text = (
            "No monthly fee"
            if not r["monthly"]
            else (f"{usd(r['monthly'])}/month" + (" — waived at your balance" if r["waived"] else ""))
        )
        why = [
            Reason(
                code="net_value",
                params={"cents": r["net"]},
                text=f"About {usd(r['net'])} over {req.holding_months} months "
                f"(interest {usd(r['interest'])} + bonus {usd(r['bonus'])} − fees "
                f"{usd(r['eff'] * req.holding_months)}).",
            )
        ]
        why.append(
            Reason(
                code="apy",
                params={"apy": str(r["apy"])},
                text=f"{r['apy'].normalize():f}% APY at your deposit level.",
            )
        )
        results.append(
            Result(
                rank=0,
                product=p,
                score=score,
                components=comps,
                values=Values(
                    ongoing_annual_cents=int(Decimal(dep_c) * r["apy"] / 100) - r["eff"] * 12,
                    promotional_cents=r["bonus"],
                    first_year_cents=r["net"],
                ),
                fee_text=fee_text,
                current_offer=r["o"],
                achievability=r["ach"],
                why=why,
                limitations=lim,
                assumptions=[
                    f"Uses about {usd(dep_c)} (the {'lower bound' if req.deposit_range == '100k_plus' else 'midpoint'}"
                    " of your range).",
                    "APY is variable; the estimate assumes the current rate stays the same.",
                    "Simple interest estimate over your holding period.",
                ],
            )
        )
    results.sort(key=lambda x: (-x.score, -x.values.first_year_cents, x.product.name))
    for n, res in enumerate(results, start=1):
        res.rank = n
    return RecommendResponse(
        product_type="savings", generated_at=now, results=results, excluded=excluded, disclaimer=DISCLAIMER
    )
