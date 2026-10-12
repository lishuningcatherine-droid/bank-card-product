"""Field-level diff and minor/major classification (DESIGN §21.3, config/change_policy.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel

from bankrec.settings import CONFIG_DIR

APR_FIELDS = [
    "purchase_apr_min_pct",
    "purchase_apr_max_pct",
    "bt_apr_min_pct",
    "bt_apr_max_pct",
    "cash_apr_pct",
]


@lru_cache(maxsize=1)
def policy() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "change_policy.yaml").read_text(encoding="utf-8")))


def jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return jsonable(v.model_dump())
    if isinstance(v, Decimal):
        return str(v.normalize()) if v == v.to_integral() else str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


@dataclass
class Change:
    field: str
    old: Any
    new: Any
    change_class: str  # minor | major | info
    rule: str


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def classify_field(name: str, old: Any, new: Any, all_apr_deltas: dict[str, Decimal]) -> tuple[str, str]:
    pol = policy()
    if name in pol.get("ignore", []):
        return "info", "ignored_field"
    if old is None or new is None:
        return "major", "value_added_or_removed"
    if name == "apy_pct":
        d = abs(Decimal(str(new)) - Decimal(str(old)))
        lim = Decimal(str(pol["minor"]["apy_pct"]["max_abs_change_pp"]))
        return ("minor", "apy_within_threshold") if d <= lim else ("major", "apy_over_threshold")
    if name == "apy_tiers":
        lim = Decimal(str(pol["minor"]["apy_tiers"]["max_abs_change_pp"]))
        if len(old) == len(new) and all(
            (a["min_balance_cents"], a["max_balance_cents"])
            == (b["min_balance_cents"], b["max_balance_cents"])
            and abs(Decimal(str(a["apy_pct"])) - Decimal(str(b["apy_pct"]))) <= lim
            for a, b in zip(old, new, strict=True)
        ):
            return "minor", "apy_tiers_within_threshold"
        return "major", "apy_tiers_changed"
    if name in APR_FIELDS:
        lim = Decimal(str(pol["minor"]["variable_apr_uniform_shift"]["max_abs_change_pp"]))
        deltas = set(all_apr_deltas.values())
        if len(deltas) == 1 and abs(next(iter(deltas))) <= lim:
            return "minor", "uniform_apr_shift"
        return "major", "non_uniform_apr_change"
    if name == "terms_url":
        if urlsplit(str(old)).hostname == urlsplit(str(new)).hostname:
            return "minor", "terms_url_same_domain"
        return "major", "terms_url_domain_changed"
    return "major", "default_major"


def diff_product(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """``old``/``new`` are product snapshots: {"fields": {...}, "reward_rates": [...], "benefits": [...]}."""
    of, nf = old.get("fields", {}), new.get("fields", {})
    # Every APR bound present on both sides must move by the same delta for a "uniform" (prime-rate) shift.
    apr_deltas = {
        k: Decimal(str(nf[k])) - Decimal(str(of[k]))
        for k in APR_FIELDS
        if of.get(k) is not None and nf.get(k) is not None
    }
    if any(of.get(k) != nf.get(k) and (of.get(k) is None or nf.get(k) is None) for k in APR_FIELDS):
        apr_deltas["__added_or_removed__"] = Decimal("999")
    changes: list[Change] = []
    for k in sorted(set(of) | set(nf)):
        if of.get(k) != nf.get(k):
            cls, rule = classify_field(k, of.get(k), nf.get(k), apr_deltas)
            changes.append(Change(k, of.get(k), nf.get(k), cls, rule))
    for k in ("reward_rates", "benefits"):
        if _canon(old.get(k)) != _canon(new.get(k)):
            changes.append(Change(k, old.get(k), new.get(k), "major", f"{k}_changed"))
    return changes


def _canon(items: list[dict[str, Any]] | None) -> list[str]:
    return sorted(repr(sorted(i.items())) for i in items or [])


def diff_offers(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], *, product_is_new: bool
) -> list[Change]:
    """Offers keyed by offer_key. Any appearance/disappearance/amount or requirement change is major."""
    changes: list[Change] = []
    for k in old.keys() - new.keys():
        changes.append(Change(f"offer:{old[k]['offer_type']}", old[k], None, "major", "offer_disappeared"))
    for k in new.keys() - old.keys():
        if product_is_new:
            continue
        rule = (
            "offer_changed"
            if any(o["offer_type"] == new[k]["offer_type"] for o in old.values())
            else "offer_appeared"
        )
        if policy().get("new_offer_on_existing_product", "review") != "review" and rule == "offer_appeared":
            changes.append(Change(f"offer:{new[k]['offer_type']}", None, new[k], "minor", rule))
        else:
            changes.append(Change(f"offer:{new[k]['offer_type']}", None, new[k], "major", rule))
    return changes
