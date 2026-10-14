"""Adapter protocol and the declarative base every bank adapter builds on (DESIGN §7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Protocol

import yaml

from bankrec.candidate import ProductCandidate
from bankrec.ingest.common import extract as X
from bankrec.ingest.common.html import PageDoc, scoped
from bankrec.model import (
    PRIORITY,
    ExtractionContext,
    NullReason,
    PageType,
    ProductType,
    ProvenanceClass,
    RewardRateRec,
    Sourced,
)
from bankrec.registry.no_rewards import confirmed as no_rewards_confirmed
from bankrec.registry.schema import BankConfig, SourceEntry
from bankrec.settings import CONFIG_DIR


@dataclass
class ClassifiedPage:
    source: SourceEntry
    bank: BankConfig
    url: str
    page_type: PageType
    retrieved_at: datetime
    text: str
    doc: PageDoc | None = None
    snapshot_id: str | None = None
    capture_method: str = "automated"
    capture_conditions: dict[str, Any] = field(default_factory=dict)


class BankAdapter(Protocol):
    bank_id: ClassVar[str]
    parser_version: ClassVar[str]

    def extract(self, page: ClassifiedPage) -> list[ProductCandidate]: ...


@lru_cache(maxsize=1)
def co_brands() -> dict[str, list[str]]:
    return yaml.safe_load((CONFIG_DIR / "co_brands.yaml").read_text(encoding="utf-8"))


def lowest_rate_per_category(rates: list[Sourced[RewardRateRec]]) -> list[Sourced[RewardRateRec]]:
    """One rate per category. The same rate is often stated twice (summary and detail); when the page shows two
    different rates for one category, the lower one is kept (never overstate)."""
    low: dict[str, Sourced[RewardRateRec]] = {}
    for r in rates:
        v = r.value
        if v is None:
            continue
        lv = low[v.category].value if v.category in low else None
        if lv is None or v.rate < lv.rate or (v.rate == lv.rate and lv.cap_cents is None and v.cap_cents):
            low[v.category] = r
    return list(low.values())


NETWORKS = [
    ("American Express", r"\bAmerican Express\b"),
    ("Visa", r"\bVisa\b"),
    ("Mastercard", r"\bMaster[Cc]ard\b"),
    ("Discover", r"\bDiscover\b(?! more)"),
]


class DeclarativeAdapter:
    """Extraction driven by optional ``config/banks/<bank_id>.rules.yaml`` selectors, with shared fallbacks."""

    bank_id: ClassVar[str] = ""
    parser_version: ClassVar[str] = ""
    rules_dir: ClassVar[Path] = CONFIG_DIR / "banks"

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        path = self.rules_dir / f"{self.bank_id}.rules.yaml"
        self.rules: dict[str, Any] = (
            rules
            if rules is not None
            else (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}) or {}
        )

    # ------------------------------------------------------------------ hooks (override in bank modules)
    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        sel = self.rules.get(f"{key}_selector")
        if sel and page.doc is not None:
            return [page.doc.node_text(n).replace("\n", " ") for n in page.doc.select(sel)]
        if fallback is None:
            return []
        return (
            X.lines(page.doc, fallback)
            if page.doc is not None
            else [ln for ln in page.text.split("\n") if re.search(fallback, ln, re.IGNORECASE)]
        )

    def product_name(self, page: ClassifiedPage) -> str | None:
        sel = self.rules.get("name_selector", "h1")
        if page.doc is not None:
            for n in page.doc.select(sel):
                t = page.doc.node_text(n).replace("\n", " ").strip()
                if t:
                    return t
        return None

    def offer_absent_note(self, page: ClassifiedPage) -> str | None:
        return self.rules.get("offer_absent_note")

    def offer_note(self, page: ClassifiedPage) -> str | None:
        return self.rules.get("offer_note")

    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        """Bank-specific additions (e.g. annual fee stated only in an FAQ answer)."""

    def partner_rates(self, c: ProductCandidate) -> None:
        """Earn on the co-brand partner itself ("2X points on Southwest Airlines purchases", "6X at hotels
        participating in Marriott Bonvoy"): for airline/hotel partners it counts as ``airline`` / ``hotel`` (which
        the recommender does not apply to broad user categories), and a rate naming the partner under some other
        category is dropped. Retail partners' merchants are not in the vocabulary, so generic categories in the same
        sentence ("gas stations and most Disney locations") stand. ``partner_words`` in the rules lists the words
        that identify the partner (default: the partner name)."""
        partner = c.value("co_brand_partner")
        if not partner:
            return
        kind = next((k for k, v in co_brands().items() if partner in v), None)
        if kind not in ("airline", "hotel"):
            return
        words = (self.rules.get("partner_words") or {}).get(partner, [partner])
        rates = []
        for r in c.reward_rates:
            v = r.value
            if v is None:
                continue
            if v.category != "other" and any(re.search(rf"\b{re.escape(w)}\b", v.text, re.I) for w in words):
                if v.category not in (kind, "travel"):
                    continue
                r = r.model_copy(update={"value": v.model_copy(update={"category": kind})})
            rates.append(r)
        c.reward_rates = rates

    def _no_rewards(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        """Owner-confirmed, evidence-backed "no rewards program" (config/no_rewards.yaml, DESIGN §24.15)."""
        if (page.bank.bank_id, page.source.slug) not in no_rewards_confirmed():
            return
        if c.reward_rates or page.page_type is not PageType.official_product_detail:
            if c.reward_rates:
                c.notes.append("no-rewards entry ignored: the product page states earn rates")
            return
        na = NullReason.not_applicable
        c.fields["rewards_program"] = ctx.field(
            "none", c.name, method="manual_review", name="rewards_program"
        )
        if c.fields["rewards_program"].present:
            c.fields["base_rate"] = ctx.field(None, None, null_reason=na)
            c.fields["reward_currency"] = ctx.field(None, None, null_reason=na)

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        """Card fees and APRs. The default reads pricing tables and "Label: value" lines."""
        assert page.doc is not None
        return X.card_fees_and_rates(page.doc, ctx)

    # ------------------------------------------------------------------ main entry
    def extract(self, page: ClassifiedPage) -> list[ProductCandidate]:
        if page.source.product_type is None:
            return []
        scope = self.rules.get("scope_selector")
        if scope and page.doc is not None:
            page = replace(page, doc=scoped(page.doc, scope, self.rules.get("exclude_selector")))
        conf = PRIORITY.get(page.page_type, 0) / 100.0
        prov = (
            ProvenanceClass.manual_capture
            if page.capture_method == "manual"
            else ProvenanceClass.official_pdf
            if page.page_type is PageType.pdf_terms
            else ProvenanceClass.official_page
        )
        ctx = ExtractionContext(page.text, source_confidence=conf, provenance_class=prov)
        c = ProductCandidate(
            bank_id=page.bank.bank_id,
            product_type=page.source.product_type,
            source_id=page.source.source_id,
            url=page.url,
            page_type=page.page_type,
            parser_name=type(self).__module__.rsplit(".", 1)[-1],
            parser_version=self.parser_version,
            retrieved_at=page.retrieved_at,
            capture_method=page.capture_method,
            snapshot_id=page.snapshot_id,
        )
        name = self.product_name(page) if page.doc is not None else page.source.expected_entity
        c.fields["official_name"] = ctx.field(name, name, method="table_cell", name="official_name")
        if page.doc is not None:
            if c.product_type is ProductType.credit_card:
                self._card(page, ctx, c)
            elif c.product_type is ProductType.checking:
                self._checking(page, ctx, c)
            else:
                self._savings(page, ctx, c)
        terms = self.rules.get("terms_link_selector")
        if terms and page.doc is not None:
            for n in page.doc.select(terms):
                href = n.attributes.get("href")
                label = page.doc.node_text(n).replace("\n", " ").strip()
                if href and href.startswith("https://") and label:
                    # value comes from the link's href in the raw HTML; the visible link text is the located span
                    c.fields["terms_url"] = ctx.field(href, label, method="table_cell", name="terms_url")
                    break
        c.fields.setdefault("terms_url", ctx.field(None, None))
        c.refused_fields = ctx.refused
        c.set_missing_defaults()
        return [c]

    # ------------------------------------------------------------------ product types
    def _card(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        name = c.name or ""
        c.fields.update(self.fees_and_rates(page, ctx))
        biz = re.search(r"\bbusiness\b", name, re.IGNORECASE)
        c.fields["segment"] = ctx.field("business" if biz else "consumer", name, method="label_regex")
        c.fields["is_student"] = ctx.field(bool(re.search(r"\bstudents?\b", name, re.I)), name)
        secured = re.search(r"\bsecured\b", name, re.IGNORECASE)
        c.fields["is_secured"] = ctx.field(bool(secured), name)
        if not secured:
            c.fields["secured_min_deposit_cents"] = ctx.field(
                None, None, null_reason=NullReason.not_applicable
            )
        partner = None
        brand_map = {k: list(v) for k, v in co_brands().items()}
        for k, v in (self.rules.get("co_brands") or {}).items():
            brand_map.setdefault(k, []).extend(v)
        for kind, brands in brand_map.items():
            for b in brands:
                if re.search(r"(?<!\w)" + re.escape(b) + r"(?!\w)", name, re.IGNORECASE):
                    partner = (b, kind)
                    break
            if partner:
                break
        c.fields["is_co_branded"] = ctx.field(partner is not None, name)
        c.fields["co_brand_partner"] = (
            ctx.field(partner[0], name)
            if partner
            else ctx.field(None, None, null_reason=NullReason.not_applicable)
        )
        found = [(n, m) for n, p in NETWORKS if (m := re.search(p, page.text))]
        if self.rules.get("network"):
            n = self.rules["network"]
            c.fields["network"] = ctx.field(n, n)
        elif len(found) == 1:
            c.fields["network"] = ctx.field(found[0][0], found[0][1].group(0))
        elif len(found) > 1:
            c.fields["network"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
        reward_lines = self.statements(
            page,
            "reward",
            r"\d(?:\.\d+)?\s*(?:%|[xX]\b|\s+(?:points|miles)\s+per)\s*.*"
            r"(?:cash back|back|points|miles|on\b)",
        )
        rates = X.reward_rates(reward_lines, ctx)
        # Rewards paid in a merchant's own currency (e.g. "Disney Rewards Dollars") are not cash back or points the
        # recommender can value: no rates, no currency (the card stays Partially verified).
        store = next(
            (m for p in self.rules.get("store_currency_patterns", []) if (m := re.search(p, page.text))), None
        )
        if store is not None:
            rates = []
            c.notes.append(f"rewards paid in store currency ({store.group(0)}); not valued")
        c.reward_rates = rates
        rate_text = " ".join(r.span_text or "" for r in rates)
        currency, _ = X.reward_currency(rates, rate_text)
        c.fields["reward_currency"] = (
            ctx.field(currency, rates[0].span_text) if currency and rates else ctx.field(None, None)
        )
        base = [r for r in rates if r.value and r.value.category == "other"]
        c.fields["base_rate"] = (
            ctx.field(base[0].value.rate, base[0].span_text)
            if base and base[0].value
            else ctx.field(None, None)
        )
        prog = self.rules.get("reward_program_pattern")
        if prog and (m := re.search(prog, page.text)):
            c.fields["reward_program"] = ctx.field(m.group(0), m.group(0))
        credit_lines = self.statements(
            page, "credit", r"\$\d[\d,]*\s+(?:\w+\s+){0,5}?(?:statement\s+)?credit"
        )
        c.benefits = X.credits(credit_lines, ctx)
        c.benefits += X.named_benefits(self.statements(page, "benefit", None), ctx)
        guide = X.first_line(doc, r"^(?:recommended credit|credit (?:level|needed|score|profile))\s*[:\-]")
        if not c.fields.get("credit_profile_guidance", Sourced(null_reason=NullReason.not_found)).present:
            c.fields["credit_profile_guidance"] = (
                ctx.field(guide.split(":", 1)[-1].strip(), guide) if guide else ctx.field(None, None)
            )
        elig = X.lines(
            doc,
            r"not available to|once per (?:lifetime|card ?member)|if you have (?:received|had)|"
            r"within the (?:last|past) \d+ months",
        )
        c.fields["eligibility_restrictions"] = (
            ctx.field(" ".join(elig), elig[0]) if elig else ctx.field(None, None)
        )
        self._offers(page, ctx, c, "card_welcome")
        self.card_extras(page, ctx, c)
        self._no_rewards(page, ctx, c)

    def _checking(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        c.fields["monthly_fee_cents"] = X.monthly_fee(doc, ctx)
        waiver_lines = self.statements(
            page,
            "waiver",
            r"(?:avoid|waive)|balance of \$|deposits? totaling|"
            r"linked|under (?:the )?age",
        )
        c.fields["fee_waivers"] = X.fee_waivers(waiver_lines, ctx)
        if c.fields["monthly_fee_cents"].value == 0:
            c.fields["fee_waivers"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        c.fields["min_opening_deposit_cents"] = X.min_amount(doc, ctx, "min_opening")
        od = X.labelled(doc, "overdraft")
        c.fields["overdraft_summary"] = ctx.field(od[0], od[1]) if od else ctx.field(None, None)
        tiers = X.apy_tiers(doc, ctx, self.rules.get("apy_tier_selector", "table.apy-tiers tr"))
        c.fields["apy_tiers"] = (
            tiers if tiers.present else ctx.field(None, None, null_reason=NullReason.not_applicable)
        )
        c.fields["eligible_states"] = X.states(page.text, ctx)
        access = self.rules.get("access_model")
        if access:
            c.fields["access_model"] = (
                ctx.field(access["value"], access["evidence"])
                if isinstance(access, dict)
                else ctx.field(None, None)
            )
        acct = X.first_line(doc, r"^account type\s*:")
        c.fields["account_type"] = (
            ctx.field(acct.split(":", 1)[1].strip(), acct) if acct else ctx.field(None, None)
        )
        elig = X.first_line(doc, r"^(?:eligibility|who can open)\s*:")
        c.fields["customer_eligibility"] = (
            ctx.field(elig.split(":", 1)[1].strip(), elig) if elig else ctx.field(None, None)
        )
        self._offers(page, ctx, c, "checking_bonus")

    def _savings(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        c.fields["apy_tiers"] = X.apy_tiers(
            doc, ctx, self.rules.get("apy_tier_selector", "table.apy-tiers tr")
        )
        # Tiered accounts: the tier table governs; a single headline APY would be misleading.
        apy = (
            ctx.field(None, None, null_reason=NullReason.not_applicable)
            if c.fields["apy_tiers"].present
            else X.apy_value(doc, ctx)
        )
        c.fields["apy_pct"] = apy
        if not c.fields["apy_tiers"].present and apy.present:
            c.fields["apy_tiers"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        var = X.first_line(doc, r"\bvariable\b|rates? (?:may|can|are subject to) change")
        c.fields["rate_type_note"] = ctx.field(var, var) if var else ctx.field(None, None)
        c.fields["min_opening_deposit_cents"] = X.min_amount(doc, ctx, "min_opening")
        c.fields["min_balance_cents"] = X.min_amount(doc, ctx, "min_balance")
        c.fields["monthly_fee_cents"] = X.monthly_fee(doc, ctx)
        waiver_lines = self.statements(page, "waiver", r"(?:avoid|waive)")
        c.fields["fee_waivers"] = (
            X.fee_waivers(waiver_lines, ctx)
            if c.fields["monthly_fee_cents"].value
            else ctx.field(None, None, null_reason=NullReason.not_applicable)
        )
        wr, wn = X.withdrawal_limit(doc, ctx)
        c.fields["withdrawal_restrictions"], c.fields["max_withdrawals_per_month"] = wr, wn
        c.fields["eligible_states"] = X.states(page.text, ctx)
        cr = X.first_line(doc, r"^(?:eligibility|who can open)\s*:")
        c.fields["customer_restrictions"] = (
            ctx.field(cr.split(":", 1)[1].strip(), cr) if cr else ctx.field(None, None)
        )
        self._offers(page, ctx, c, "savings_bonus")

    def _offers(
        self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate, offer_type: str
    ) -> None:
        blocks = self.statements(
            page,
            "offer",
            r"(?:bonus|welcome offer|earn \$\d|earn up to)[^\n]*"
            r"(?:after|when|with|\d)",
        )
        foot = " ".join(self.statements(page, "offer_footnote", r"^[*†‡]"))
        tiers = self.statements(page, "offer_tier", None)
        for b in blocks[:3]:
            o = X.offer(
                b,
                foot,
                ctx,
                offer_type=offer_type,
                offer_url=page.url,
                tiers=tiers,
                note=self.offer_note(page),
            )
            if o is not None:
                c.offers.append(o)
        if not c.offers:
            c.offer_absent_note = self.offer_absent_note(page)
