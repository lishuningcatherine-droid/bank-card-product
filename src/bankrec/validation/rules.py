"""Validation rules (brief §7.3–7.4). Products and offers are validated independently."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bankrec.candidate import ProductCandidate
from bankrec.model import EXTRACTABLE_PAGE_TYPES, NullReason, OfferRec, PageType, Sourced
from bankrec.parsers.offers import _VAR
from bankrec.registry.urls import domain_allowed
from bankrec.settings import CONFIG_DIR


@lru_cache(maxsize=4)
def policy(path: Path | None = None) -> dict[str, Any]:
    return dict(yaml.safe_load((path or CONFIG_DIR / "validation.yaml").read_text(encoding="utf-8")))


@dataclass
class RuleResult:
    rule_id: str
    severity: str  # error | review | info
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class OfferVerdict:
    index: int
    status: str  # valid | needs_review | reject
    results: list[RuleResult]


@dataclass
class Verdict:
    status: str  # valid | needs_review | reject
    confidence: float
    results: list[RuleResult]
    missing_required: list[str]
    missing_key: list[str]
    offers: list[OfferVerdict]

    @property
    def failed(self) -> list[RuleResult]:
        return [r for r in self.results if not r.ok]


def _field_present(c: ProductCandidate, name: str) -> bool:
    if name == "apy":
        return (
            c.fields.get("apy_pct", Sourced(null_reason=NullReason.not_found)).present
            or c.fields.get("apy_tiers", Sourced(null_reason=NullReason.not_found)).present
        )
    f = c.fields.get(name)
    return f is not None and (f.present or f.null_reason is NullReason.not_applicable)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"[®™℠]", "", s.lower())).strip()


def check_name(c: ProductCandidate, page_text: str) -> RuleResult:
    name = c.name
    if not name or not name.strip():
        return RuleResult("R-NAME", "error", False, "product name missing")
    if _norm(name) in {_norm(g) for g in policy()["generic_names"]}:
        return RuleResult("R-NAME", "error", False, f"generic name {name!r}")
    if _norm(name) not in _norm(page_text):
        return RuleResult("R-NAME", "error", False, "name not found in page text")
    return RuleResult("R-NAME", "error", True, "ok")


def validate_offer(o: OfferRec, capture_ok: bool) -> list[RuleResult]:
    res: list[RuleResult] = []
    var = _VAR.search(o.verbatim_text)
    res.append(
        RuleResult(
            "V-QUALIFIER",
            "error",
            not (o.amount_qualifier == "exact" and var is not None and not o.tiers),
            "exact amount stated with variability language" if var else "ok",
            {"phrase": var.group(0) if var else None},
        )
    )
    if o.qualification_window_days is not None:
        res.append(
            RuleResult("C-WINDOW", "error", o.qualification_window_days > 0, "qualification window > 0")
        )
    if o.start_date and o.expiration_date:
        res.append(
            RuleResult("C-OFFER-DATES", "error", o.start_date <= o.expiration_date, "start <= expiration")
        )
    res.append(RuleResult("R-CAPTURE", "error", capture_ok, "public default capture conditions recorded"))
    res.append(RuleResult("R-AUDIENCE", "review", o.audience == "public", "offer audience is public"))
    has_req = o.requirement_type is not None or o.offer_type in {"intro_apr", "annual_fee_waiver"}
    res.append(RuleResult("R-OFFER-REQ", "review", has_req, "requirement identified"))
    return res


def _status(results: list[RuleResult]) -> str:
    if any(not r.ok and r.severity == "error" for r in results):
        return "reject"
    if any(not r.ok and r.severity == "review" for r in results):
        return "needs_review"
    return "valid"


def validate(
    c: ProductCandidate,
    page_text: str,
    official_domains: list[str],
    *,
    fresh: bool = True,
    capture_ok: bool = True,
    conflicts: list[dict[str, Any]] | None = None,
) -> Verdict:
    pol = policy()
    sanity = pol["sanity"]
    t = c.product_type.value
    res: list[RuleResult] = [check_name(c, page_text)]
    res.append(
        RuleResult("R-DOMAIN", "error", domain_allowed(c.url, official_domains), f"official domain: {c.url}")
    )
    res.append(
        RuleResult("R-PAGE", "error", c.page_type in EXTRACTABLE_PAGE_TYPES, f"page type {c.page_type}")
    )
    res.append(
        RuleResult(
            "R-DETAIL",
            "review",
            c.page_type is not PageType.official_comparison_page,
            "comparison-page values need confirmation from a detail page or review",
        )
    )
    missing_required = [f for f in pol["required"][t] if not _field_present(c, f)]
    missing_key = [f for f in pol["key"][t] if not _field_present(c, f)]
    res.append(
        RuleResult(
            "R-REQ", "review", not missing_required, "required fields present", {"missing": missing_required}
        )
    )
    requires_render = [k for k, v in c.fields.items() if v.null_reason is NullReason.requires_render]
    if requires_render:
        res.append(
            RuleResult(
                "R-PLACEHOLDER",
                "info",
                True,
                "placeholder values recorded as missing",
                {"fields": requires_render},
            )
        )
    v = c.value
    if t == "credit_card":
        intro, pmin = v("intro_purchase_apr_pct"), v("purchase_apr_min_pct")
        if intro is not None and pmin is not None:
            res.append(
                RuleResult(
                    "C-INTRO-APR", "review", Decimal(intro) < Decimal(pmin), "intro APR < purchase APR"
                )
            )
        fee = v("annual_fee_cents")
        if fee is not None:
            res.append(
                RuleResult(
                    "C-FEE",
                    "review",
                    0 <= fee <= sanity["card_annual_fee_max_cents"],
                    "annual fee within sane range",
                )
            )
        for k in ("purchase_apr_min_pct", "purchase_apr_max_pct"):
            if v(k) is not None:
                res.append(
                    RuleResult("C-APR", "review", 0 <= Decimal(v(k)) <= sanity["apr_max_pct"], f"{k} sane")
                )
        base = v("base_rate")
        if base is not None:
            low = [
                r.value.category
                for r in c.reward_rates
                if r.value
                and r.value.category != "other"
                and r.value.rate < Decimal(base)
                and r.value.rate_unit == r.value.rate_unit
            ]
            res.append(RuleResult("C-CAT>=BASE", "review", not low, "category rate >= base", {"below": low}))
    else:
        fee = v("monthly_fee_cents")
        if fee is not None:
            res.append(
                RuleResult(
                    "C-FEE",
                    "review",
                    0 <= fee <= sanity["deposit_monthly_fee_max_cents"],
                    "monthly fee within sane range",
                )
            )
        apy = v("apy_pct")
        if apy is not None:
            res.append(
                RuleResult("C-APY", "review", 0 <= Decimal(apy) <= sanity["apy_max_pct"], "APY in [0, 15]")
            )
        tiers = v("apy_tiers") or []
        if tiers:
            ok = all(0 <= Decimal(tt.apy_pct) <= sanity["apy_max_pct"] for tt in tiers) and all(
                a.min_balance_cents < b.min_balance_cents for a, b in itertools.pairwise(tiers)
            )
            res.append(RuleResult("C-TIERS", "review", ok, "APY tiers ordered and within range"))
    res.append(RuleResult("F-FRESH", "review", fresh, "retrieved within freshness window"))
    for cf in conflicts or []:
        res.append(RuleResult("X-CONFLICT", "review", False, f"conflicting values for {cf['field']}", cf))

    req_conf = [c.fields[f].confidence for f in pol["required"][t] if f in c.fields and c.fields[f].present]
    if "apy" in pol["required"][t]:
        req_conf += [
            c.fields[f].confidence for f in ("apy_pct", "apy_tiers") if f in c.fields and c.fields[f].present
        ]
    confidence = min(req_conf) if req_conf else 0.0
    res.append(
        RuleResult(
            "R-CONFIDENCE",
            "review",
            confidence >= pol["confidence_threshold"],
            "confidence at or above threshold",
        )
    )

    offers = []
    for i, so in enumerate(c.offers):
        if so.value is None:
            continue
        ors = validate_offer(so.value, capture_ok)
        offers.append(OfferVerdict(i, _status(ors), ors))
    return Verdict(_status(res), round(confidence, 4), res, missing_required, missing_key, offers)
