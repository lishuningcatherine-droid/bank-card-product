"""Adapter protocol and the declarative base every bank adapter builds on (DESIGN §7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, ClassVar, Protocol

import yaml

from bankrec.candidate import ProductCandidate
from bankrec.ingest.common import deposits as D
from bankrec.ingest.common import extract as X
from bankrec.ingest.common.html import PageDoc, parse_html, scoped
from bankrec.model import (
    PRIORITY,
    ApyTier,
    ExtractionContext,
    NullReason,
    PageType,
    ProductType,
    ProvenanceClass,
    RateCondition,
    RewardRateRec,
    Sourced,
)
from bankrec.normalize.categories import categories_in
from bankrec.parsers.rewards import parse_rate_only, parse_reward_statement, strip_exclusions
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
    """One rate per category and channel. The same rate is often stated twice (summary and detail); when the page
    shows two different rates for one category, the lower one is kept (never overstate). A portal-only rate ("5x on
    Chase Travel") and the general rate for the same category ("2x on all other travel") are different rates and are
    both kept (spot-check round 1, finding 1). So are a time-bound rate and the ongoing one ("2X at grocery stores.
    Through December 31, 2026, these purchases will earn 3X"; round 2)."""
    low: dict[tuple[str, bool, object, object], Sourced[RewardRateRec]] = {}
    for r in rates:
        v = r.value
        if v is None:
            continue
        # partner / merchant rates at different values are different merchants ("10% at DisneyPlus.com ..." and "3% at
        # most U.S. Disney locations"), not two readings of one rate
        k = (v.category, v.portal_only, v.ends_on, v.rate if v.category in {"partner", "merchant"} else None)
        lv = low[k].value if k in low else None
        if lv is None or v.rate < lv.rate or (v.rate == lv.rate and lv.cap_cents is None and v.cap_cents):
            low[k] = r
    # "5x on Lyft rides" (a tile heading) and "Earn 5x on Lyft rides through 9/30/27" are one rate: the dated one.
    dated = {(v.category, v.portal_only, v.rate) for r in low.values() if (v := r.value) and v.ends_on}
    return [
        r
        for r in low.values()
        if (v := r.value) is not None
        and (v.ends_on is not None or (v.category, v.portal_only, v.rate) not in dated)
    ]


# Rate-like text that is never an earn statement: APRs, review percentages, bare numbers, calculator labels.
def _partner_probe(st: str, words: list[str]) -> str:
    """``st`` with the partner's purchases replaced by "partner purchases" (``st`` unchanged when not found)."""
    pat = "|".join(re.escape(w) for w in words)
    probe = re.sub(
        rf"(?:eligible\s+)?(?:entire\s+)?(?:{pat})(?:[®™]|\s|,)*(?:[\w.®™]+,?\s+){{0,6}}?(?:purchases?|orders|locations)\b"
        r"(?:\s*\([^)]*\))?",  # "Allegiant purchases (air, hotel, car rental and attractions)"
        "partner purchases",
        st,
        count=1,
        flags=re.I,
    )
    if probe == st:  # "... on qualifying purchases made using your card directly through Instacart"
        probe = re.sub(
            rf"\b(?:qualifying\s+)?purchases\b[^.]{{0,80}}?\b(?:through|at|with|on)\s+(?:the\s+)?(?:{pat})\b",
            "partner purchases",
            st,
            count=1,
            flags=re.I,
        )
    return probe


_NOT_AN_EARN_STATEMENT = re.compile(
    # APR (also "APR2" with a footnote digit), fee and credit-score copy, and store-discount copy are not earn rates
    r"\bAPR(?:\b|\d)|transfer fee|of each transfer|credit score|\bsavings everyday\b|respondents|recommend this|^\s*\d{1,3}(?:\.\d+)?%\s*$|^\s*[\d.]+%\s*-\s*[\d.]+%|^earn \d+% cash back\.?$",
    re.IGNORECASE,
)

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

    def _partner_merchant_rates(
        self,
        lines: list[str],
        rates: list[Sourced[RewardRateRec]],
        partner: tuple[str, str] | None,
        ctx: ExtractionContext,
    ) -> list[Sourced[RewardRateRec]]:
        """A rate on the co-brand partner's own purchases ("4% cash back on DoorDash and Caviar orders", "3 points per
        dollar spent on eligible Royal Caribbean® ... purchases") is a ``partner`` rate: stored and shown, never
        applied to the user's spend categories."""
        if partner is None:
            return []
        words = self._partner_words(partner[0])
        out: list[Sourced[RewardRateRec]] = []
        for st in lines:
            if not any(re.search(rf"\b{re.escape(w)}\b", self._mask_currency(st), re.I) for w in words):
                continue  # "Earn 1% in Disney Rewards Dollars on all card purchases" names the currency, not Disney
            probe = _partner_probe(self._mask_currency(st), words)
            rr = parse_reward_statement(probe) if probe != st else None
            # "3 points on eligible dining, foreign transaction, Alaska Airlines and Hawaiian Airlines purchases":
            # the partner part is a partner rate; dining stays a dining rate (from the ordinary parse).
            if rr is None or "partner" not in rr.categories:
                continue
            plain = parse_reward_statement(st)
            if (
                partner[1] in ("airline", "hotel")
                and plain is not None
                and any(k in (partner[1], "travel") for k in plain.categories)
            ):
                continue  # "3 Avios on British Airways ... flight purchases" is already the airline rate
            rec = RewardRateRec(
                category="partner",
                rate=rr.rate,
                rate_unit=rr.rate_unit,
                cap_cents=rr.cap_cents,
                cap_period=rr.cap_period,
                cap_combined=rr.cap_combined,
                post_cap_rate=rr.post_cap_rate,
                portal_only=rr.portal_only,
                requires_activation=rr.requires_activation,
                ends_on=rr.ends_on,
                text=st.strip(),
            )
            got = ctx.field(rec, st, method="free_text", name="reward:partner")
            if got.present and X.norm_ws(st) not in {X.norm_ws(r.span_text or "") for r in out}:
                out.append(got)
        return out

    def _category_exclusions(self, page: ClassifiedPage, c: ProductCandidate) -> None:
        """Page sentences that take superstores / warehouse clubs out of a category ("Superstores and warehouse clubs
        are not considered supermarkets") become conditions on that category's rates, quoting the sentence."""
        found = X.category_exclusions(page.text)
        if not found:
            return
        out = []
        for r in c.reward_rates:
            v = r.value
            if v is not None and (
                add := [
                    x
                    for cat, x in found
                    if cat == v.category and x.kind not in {y.kind for y in v.conditions}
                ]
            ):
                r = r.model_copy(update={"value": v.model_copy(update={"conditions": [*v.conditions, *add]})})
            out.append(r)
        c.reward_rates = out

    def _program_rates(
        self,
        page: ClassifiedPage,
        ctx: ExtractionContext,
        rates: list[Sourced[RewardRateRec]],
        partner: tuple[str, str] | None,
    ) -> tuple[list[Sourced[RewardRateRec]], list[str]]:
        """Earn rates the page states outside the collected earn statements (spot-check round 2, B): "That's 5X points
        with this card" tiles under a partner heading, and the rewards-program terms printed on the page ("You'll earn
        3 points for each $1 spent on purchases that post to your account through December 31, 2026 in the following
        rewards categories: utilities; ..."). A rate already represented (same rate and category; a co-brand partner
        rate stands for its airline / hotel) is skipped; a missing one is added with the terms sentence as its span.
        Returns (added rates, sentences that could not be represented). The latter make the card incomplete."""
        words = self._partner_words(partner[0]) if partner else []
        pool = list(rates)
        added: list[Sourced[RewardRateRec]] = []
        unrep: list[str] = []
        twins = {"partner", "hotel", "airline"}

        def represented(rate: Decimal, unit: str, cat: str, cap: int | None = None) -> bool:
            # a page rate without the cap the terms state is not the same rate (and adapters drop such rates)
            return any(
                (v := r.value) is not None
                and v.rate == rate
                and v.rate_unit == unit
                and (v.category == cat or (partner is not None and {v.category, cat} <= twins))
                and (cap is None or v.cap_cents == cap)
                for r in pool
            )

        sources = X.card_tiles(page.text) + X.program_statements(page.text)
        for span, st in sources:
            rr = parse_reward_statement(st)
            if rr is None or not rr.categories:
                only = parse_rate_only(st)
                names_partner = any(re.search(rf"\b{re.escape(w)}\b", st, re.I) for w in words)
                if only is not None and names_partner and represented(only[0], only[1], "partner"):
                    continue  # "3 points ... on purchases made directly with Southwest Airlines®"
                unrep.append(span)
                continue
            missing = [k for k in rr.categories if not represented(rr.rate, rr.rate_unit, k, rr.cap_cents)]
            if not missing:
                continue
            if X.PURCHASE_SIZE.search(st) or (
                missing == ["other"] and any(r.value and r.value.category == "other" for r in pool)
            ):
                unrep.append(
                    span
                )  # "2.5% ... on every purchase totaling $5,000 or more": no category to hold it
                continue
            for k in missing:
                rec = RewardRateRec(
                    category=k,
                    rate=rr.rate,
                    rate_unit=rr.rate_unit,
                    cap_cents=rr.cap_cents,
                    cap_period=rr.cap_period,
                    cap_combined=rr.cap_combined,
                    cap_group=(span if rr.cap_combined else None),
                    post_cap_rate=rr.post_cap_rate,
                    is_rotating=rr.is_rotating,
                    requires_activation=rr.requires_activation,
                    portal_only=rr.portal_only,
                    ends_on=rr.ends_on,
                    text=X.norm_ws(span),
                    conditions=X.rate_conditions(rr.conditions.get(k, []), span),
                )
                got = ctx.field(rec, span, method="free_text", name=f"reward:{k}:program_terms")
                if got.present:
                    added.append(got)
                    pool.append(got)
                else:
                    unrep.append(span)
        return added, unrep

    def _mask_currency(self, text: str) -> str:
        """``text`` without the names of restricted currencies ("Disney Rewards Dollars" is not a Disney purchase)."""
        for spec in self.rules.get("restricted_currencies") or []:
            text = re.sub(spec["detect"], "Rewards Dollars", text)
        return text

    def _restricted_currency(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        na = NullReason.not_applicable
        for spec in self.rules.get("restricted_currencies") or []:
            name = re.search(spec["detect"], page.text)
            if name is None:
                continue
            c.fields["reward_currency"] = ctx.field("restricted", name.group(0), method="free_text")
            c.fields["reward_currency_name"] = ctx.field(spec["name"], name.group(0), method="free_text")
            val = re.search(spec["value"], page.text)
            c.fields["redemption_value_cents"] = (
                ctx.field(round(float(val.group(1)) * 100), val.group(0), method="free_text")
                if val
                else ctx.field(None, None)
            )
            seen: list[str] = []
            keys: set[str] = set()
            for m in re.finditer(spec["restriction"], page.text):
                k = re.sub(
                    r"^.*?\bstatement credit toward\s+", "", X.norm_ws(m.group(0))
                )  # same place, other wording
                if k not in keys:
                    keys.add(k)
                    seen.append(X.norm_ws(m.group(0)))
            located = [s for s in seen if ctx.locate(s) is not None]
            c.fields["redemption_restriction"] = (
                ctx.field(" ".join(located), located[0], method="free_text")
                if located
                else ctx.field(None, None)
            )
            if not located:
                c.notes.append(f"{spec['name']}: where they can be redeemed is not stated on the page")
            return
        for f in ("reward_currency_name", "redemption_value_cents", "redemption_restriction"):
            c.fields[f] = ctx.field(None, None, null_reason=na)

    def _partner_words(self, partner: str) -> list[str]:
        return list((self.rules.get("partner_words") or {}).get(partner, [partner]))

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
        words = self._partner_words(partner)
        rates = []
        for r in c.reward_rates:
            v = r.value
            if v is None:
                continue
            # "travel (excluding ... hotels participating in IHG ...)" is not IHG's; "Disney Rewards Dollars" is not Disney
            named = self._mask_currency(strip_exclusions(v.text))
            if v.category not in ("other", "partner") and any(
                re.search(rf"\b{re.escape(w)}\b", named, re.I) for w in words
            ):
                if v.category not in (kind, "travel"):
                    # A category the sentence lists besides the partner ("dining, ..., Alaska Airlines purchases")
                    # stands; one that only describes the partner's purchases ("Allegiant purchases (air, hotel
                    # ...)") is dropped (the partner rate represents it).
                    if v.category in categories_in(_partner_probe(v.text, words)):
                        rates.append(r)
                    continue
                v = v.model_copy(update={"category": kind})
                r = r.model_copy(update={"value": v})
            if v.category == kind and not any(x.kind == "partner_only" for x in v.conditions):
                # "6X at hotels participating in Marriott Bonvoy": the rate is the partner's, not hotels in general
                hit = next(
                    (m for w in words if (m := re.search(rf"\b{re.escape(w)}\b[^,.;]*", named, re.I))), None
                )
                if hit is not None:
                    quote = re.split(r"\s+That[’']s\b", X.norm_ws(hit.group(0)))[0]
                    cond = RateCondition(kind="partner_only", text=quote, detail=partner)
                    r = r.model_copy(
                        update={"value": v.model_copy(update={"conditions": [*v.conditions, cond]})}
                    )
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
        if (
            page.doc is None
            and page.text
            and page.source.product_type in (ProductType.checking, ProductType.savings)
        ):
            # deposit rate sheets are PDFs: the same line readers run on the PDF text (one paragraph per line)
            html = "".join(f"<p>{escape(ln)}</p>" for ln in page.text.split("\n") if ln.strip())
            page = replace(page, doc=parse_html(f"<html><body>{html}</body></html>"))
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
        expected = page.source.expected_entity
        if (
            page.doc is not None
            and (
                c.product_type is not ProductType.credit_card
                or page.source.source_kind.value == "offer_detail"
            )
            and expected != "multiple"
            and (not name or X.norm_ws(name).lower() != X.norm_ws(expected).lower())
            and ctx.locate(expected) is not None
        ):
            # Deposit pages often head with a slogan ("A fee-free online checking account") or an eyebrow ("EVERYDAY
            # CHECKING Chase Total Checking®"), and offer pages with the bonus ("Enjoy a $400 checking account
            # bonus"): the curated product name is used when the page states it verbatim.
            name = expected
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
        ftf = c.fields.get("foreign_tx_fee_pct")
        bare = (
            ftf is not None
            and ftf.present
            and re.fullmatch(r"no foreign transaction fees?", ftf.span_text or "", re.I)
        )
        # Balance-transfer terms stated in the pricing footnotes ("Balance Transfer fee of 5% of each transfer amount,
        # $5 minimum will apply."; "... applies to balance transfers made within 60 days of account opening ...")
        btf = c.fields.get("bt_fee_pct")
        if (btf is None or not btf.present) and (bt := X.bt_fee_sentence(page.text)) is not None:
            c.fields["bt_fee_pct"] = ctx.field(bt[0], bt[2], method="free_text")
            if bt[1] is not None:
                c.fields["bt_fee_min_cents"] = ctx.field(bt[1], bt[2], method="free_text")
        btw = X.bt_window(page.text)
        bti = c.fields.get("intro_bt_apr_pct")
        if btw is not None:
            c.fields["intro_bt_window_days"] = ctx.field(btw[0], btw[1], method="free_text")
        elif bti is None or not bti.present:
            c.fields["intro_bt_window_days"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        # Fee facts stated in an FAQ / accordion answer that names the card (spot-check round 2, E); preferred as
        # evidence over a bare "No Foreign Transaction Fees" heading.
        if (ftf is None or not ftf.present or bare) and (st := X.stated_no_ftf(page.text, name)) is not None:
            c.fields["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), st, method="free_text", name="ftf_faq")
        # The intro period keeps the unit the page states (spot-check round 1, finding 7): never shown as months
        # when the page says billing cycles. The count stays in intro_*_months; this field names its unit.
        intro = c.fields.get("intro_purchase_apr_months") or c.fields.get("intro_bt_apr_months")
        if intro is not None and intro.present and intro.span_text:
            sp = intro.span_text.lower()
            unit = (
                "billing_cycles"
                if "billing cycle" in sp
                else "statement_closings"
                if "statement closing" in sp
                else "months"
                if "month" in sp
                else None
            )
            c.fields["intro_apr_period_unit"] = (
                ctx.field(unit, intro.span_text, method="label_regex") if unit else ctx.field(None, None)
            )
        biz = re.search(r"\bbusiness\b", name, re.IGNORECASE)
        c.fields["segment"] = ctx.field("business" if biz else "consumer", name, method="label_regex")
        c.fields["is_student"] = ctx.field(bool(re.search(r"\bstudents?\b", name, re.I)), name)
        secured = re.search(r"\bsecured\b", name, re.IGNORECASE)
        c.fields["is_secured"] = ctx.field(bool(secured), name)
        if not secured:
            for f in ("secured_min_deposit_cents", "secured_max_deposit_cents"):
                c.fields[f] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        else:
            # Secured cards need both ends of the deposit range (spot-check round 2, F).
            lo, hi, ev, note = X.deposit_range(page.text)
            cur = c.fields.get("secured_min_deposit_cents")
            if lo is not None and (cur is None or not cur.present):
                c.fields["secured_min_deposit_cents"] = ctx.field(lo, ev, method="free_text")
            c.fields["secured_max_deposit_cents"] = (
                ctx.field(hi, ev, method="free_text")
                if hi is not None
                else ctx.field(None, None, null_reason=NullReason.ambiguous if note else NullReason.not_found)
            )
            if note:
                c.notes.append(note)
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
        rates += self._partner_merchant_rates(reward_lines, rates, partner, ctx)
        added, unrepresented = self._program_rates(page, ctx, rates, partner)
        rates += added
        # Completeness (spot-check round 1): every rate-led earn statement the adapter collected must produce a rate.
        # Statements an adapter excludes on purpose (portal duplicates, "up to"/"total" stacked rates, discounts,
        # statement-credit rebates) never reach this list.
        produced = {X.norm_ws(r.span_text or "") for r in rates}
        unparsed = [
            st
            for line in reward_lines
            for st in [
                p.strip() for p in X.split_rate_clauses(line)
            ]  # every clause holding a rate must produce one
            if X.norm_ws(st) not in produced
            and X.has_rate_token(st)
            and not _NOT_AN_EARN_STATEMENT.search(st)
        ]
        # A short summary heading that repeats a represented rate ("Earn 5% cash back on business essentials") adds
        # no new earn rate.
        shown = {(r.value.rate, r.value.rate_unit) for r in rates if r.value}
        unparsed = [
            st
            for st in unparsed
            if not (len(st) <= 90 and (h := parse_rate_only(st)) is not None and h in shown)
        ]
        # "Earn 3 points per $1 on the first $150,000 spent in combined purchases in the following categories ...": the
        # categories are listed in the rewards-program terms, whose rates (same rate, same cap) now represent it.
        unparsed = [
            st
            for st in unparsed
            if not (
                (h := parse_rate_only(st)) is not None
                and any(
                    (v := a.value) is not None
                    and (v.rate, v.rate_unit) == h
                    and v.cap_cents is not None
                    and f"${v.cap_cents // 100:,}" in st
                    for a in added
                )
            )
        ]
        if added:
            c.notes.append(
                "earn rates read from the rewards-program terms / card tiles on the page: "
                + " | ".join(f"{r.value.rate} {r.value.category}" for r in added if r.value)
            )
        if unrepresented:
            c.notes.append(
                "rewards-program terms not represented: " + " | ".join(u[:120] for u in unrepresented)
            )
        if unparsed or unrepresented:
            c.fields["earn_rates_complete"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
            if unparsed:
                c.notes.append("earn statements not represented: " + " | ".join(u[:120] for u in unparsed))
        else:
            c.fields["earn_rates_complete"] = ctx.field(True, rates[0].span_text if rates else name)
        # Rewards paid in a merchant's own currency (e.g. "Disney Rewards Dollars") are not cash back or points the
        # recommender can value: no rates, no currency (the card stays Partially verified).
        # Store currencies not yet modelled as restricted currencies (Capital One T-Mobile / REI): not valued.
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
        # Rewards paid in a merchant's own currency ("Disney Rewards Dollars"): a restricted-redemption currency with
        # its stated value and where it can be redeemed (DESIGN §24.19), never generic cash back.
        self._restricted_currency(page, ctx, c)
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
        before = [r for r in c.reward_rates if r.value]
        self.card_extras(page, ctx, c)
        # An adapter's post-processing (partner rules, shared caps, dedupe) may drop a rate. That is fine when its
        # category is still represented, or its statement still produced a rate (e.g. a partner rate); otherwise
        # the card's earn rates are no longer complete.
        after = [r for r in c.reward_rates if r.value]
        kept = {(r.value.category, r.value.portal_only) for r in after if r.value}
        spans = {X.norm_ws(r.span_text or "") for r in after}
        lost = [
            r
            for r in before
            if r.value
            and (r.value.category, r.value.portal_only) not in kept
            and X.norm_ws(r.span_text or "") not in spans
        ]
        if lost and (done := c.fields.get("earn_rates_complete")) is not None and done.present:
            c.fields["earn_rates_complete"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
            c.notes.append(
                "earn rates dropped without replacement: "
                + " | ".join(f"{r.value.category}: {(r.span_text or '')[:100]}" for r in lost if r.value)
            )
        self._category_exclusions(page, c)
        self._no_rewards(page, ctx, c)

    def page_is_scoped(self, page: ClassifiedPage) -> bool:
        """True while reading one account of a multi-account page (page-wide readers would mix accounts)."""
        return False

    def deposit_lines(self, page: ClassifiedPage) -> list[str]:
        """The lines deposit readers work on (an adapter narrows them to one account on multi-account pages)."""
        return [ln for ln in (page.doc.text if page.doc is not None else page.text).split("\n") if ln.strip()]

    def _deposit_fee_and_waivers(
        self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate
    ) -> None:
        doc = page.doc
        assert doc is not None
        lines = self.deposit_lines(page)
        scoped_page = self.page_is_scoped(page)
        lab = None if scoped_page else X.labelled(doc, "monthly_fee")
        if lab is not None:
            fee = X.monthly_fee(doc, ctx)
        elif (f := D.monthly_fee(lines)) is not None:
            fee = ctx.field(f[0], f[1], method="label_regex", name="monthly_fee")
        else:
            fee = ctx.field(None, None) if scoped_page else X.monthly_fee(doc, ctx)
        c.fields["monthly_fee_cents"] = fee
        if self.rules.get("waiver_selector"):
            waivers = X.fee_waivers(self.statements(page, "waiver", None), ctx)
        else:
            listed = D.waiver_lines(lines)
            located = [w for w in listed if ctx.locate(w) is not None]
            waivers = (
                ctx.field(
                    [D.parse_waiver(w) for w in located], located[0], method="label_regex", name="fee_waivers"
                )
                if located and len(located) == len(listed)
                else ctx.field(
                    None, None, null_reason=NullReason.ambiguous if listed else NullReason.not_found
                )
            )
        c.fields["fee_waivers"] = waivers
        # the new-account waiver is often a footnote ("3 New and converted accounts will not be charged a Monthly
        # Service Fee for at least the first two statement periods."), outside a scope selector's main content
        iw = D.intro_fee_waiver(lines) or (
            None if scoped_page else D.intro_fee_waiver([ln for ln in page.text.split("\n") if ln.strip()])
        )
        c.fields["intro_fee_waiver"] = (
            ctx.field(iw[0], iw[1], method="label_regex", name="intro_fee_waiver")
            if iw and ctx.locate(iw[1]) is not None
            else ctx.field(None, None)
        )
        if fee.value == 0:
            c.fields["fee_waivers"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
            c.fields["intro_fee_waiver"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        # a rate sheet lists many products ("Minimum to open: $1,000 CDs / $1,000 IRAs"): its generic labels are
        # never read as this account's opening deposit
        rate_sheet = page.page_type in (PageType.pdf_terms, PageType.terms_page)
        generic_ok = not scoped_page and not rate_sheet
        if generic_ok and X.labelled(doc, "min_opening") is not None:
            opening = X.min_amount(doc, ctx, "min_opening")
        elif (o := D.opening_deposit(lines)) is not None:
            opening = ctx.field(o[0], o[1], method="label_regex", name="min_opening")
        else:
            opening = X.min_amount(doc, ctx, "min_opening") if generic_ok else ctx.field(None, None)
        c.fields["min_opening_deposit_cents"] = opening

    @staticmethod
    def _account_eligibility(ctx: ExtractionContext, lines: list[str]) -> Sourced[Any]:
        e = D.account_eligibility(lines)
        return (
            ctx.field(e, e, method="label_regex")
            if e and ctx.locate(e) is not None
            else ctx.field(None, None)
        )

    def _checking(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        lines = self.deposit_lines(page)
        self._deposit_fee_and_waivers(page, ctx, c)
        od = None if self.page_is_scoped(page) else X.labelled(doc, "overdraft")
        if od is None and (s := D.overdraft_summary(lines)) is not None:
            od = (s, s, "free_text")
        c.fields["overdraft_summary"] = ctx.field(od[0], od[1]) if od else ctx.field(None, None)
        tiers = X.apy_tiers(doc, ctx, self.rules.get("apy_tier_selector", "table.apy-tiers tr"))
        if not tiers.present and (ft := D.footnote_apy_tiers(lines)) is not None:
            # "A rate of 0.001% Annual Percentage Yield (APY) applies to accounts with balances between $0–$24,999.99.
            # A rate of 0.005% APY applies to accounts with balances of $25,000.00 or more."
            tiers = ctx.field(
                [ApyTier(min_balance_cents=a, max_balance_cents=b, apy_pct=r) for a, b, r in ft[0]],
                ft[1],
                method="label_regex",
                name="apy_tiers",
            )
        if not tiers.present and (h := D.headline_apy(lines)) is not None:
            # "Earn a 1.00% APY ...": one rate for every balance
            tiers = ctx.field(
                [ApyTier(min_balance_cents=0, max_balance_cents=None, apy_pct=h[0])], h[1], method="free_text"
            )
        elif not tiers.present and any(
            re.search(r"\bNaN\b.{0,40}(?:APY|Annual Percentage Yield)", ln) for ln in lines
        ):
            tiers = ctx.field(None, None, null_reason=NullReason.requires_render)
        c.fields["apy_tiers"] = (
            tiers
            if tiers.present or tiers.null_reason is NullReason.requires_render
            else ctx.field(None, None, null_reason=NullReason.not_applicable)
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
            ctx.field(elig.split(":", 1)[1].strip(), elig) if elig else self._account_eligibility(ctx, lines)
        )
        self._offers(page, ctx, c, "checking_bonus")

    def _savings(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        c.fields["apy_tiers"] = X.apy_tiers(
            doc, ctx, self.rules.get("apy_tier_selector", "table.apy-tiers tr")
        )
        if (
            not c.fields["apy_tiers"].present
            and (bt := D.balance_tiers(self.deposit_lines(page))) is not None
        ):
            c.fields["apy_tiers"] = ctx.field(
                [ApyTier(min_balance_cents=a, max_balance_cents=b, apy_pct=r) for a, b, r in bt[0]],
                bt[1],
                method="table_cell",
                name="apy_tiers",
            )
        # Tiered accounts: the tier table governs; a single headline APY would be misleading.
        lines = self.deposit_lines(page)
        got = D.rate_table_apy(lines) or D.headline_apy(lines)
        labelled_apy = X.labelled(doc, "apy") is not None
        apy: Sourced[Any]
        if c.fields["apy_tiers"].present:
            apy = ctx.field(None, None, null_reason=NullReason.not_applicable)
        elif not labelled_apy and got is not None:
            apy = ctx.field(got[0], got[1], method="label_regex", name="apy")
        elif not labelled_apy and any(
            re.search(r"\bNaN\b\s*(?:APY|Annual Percentage Yield)", ln) for ln in lines
        ):
            apy = ctx.field(None, None, null_reason=NullReason.requires_render)  # filled by the page script
        else:
            apy = X.apy_value(doc, ctx)
        c.fields["apy_pct"] = apy
        if not c.fields["apy_tiers"].present and apy.present:
            c.fields["apy_tiers"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        var = X.first_line(doc, r"\bvariable\b|rates? (?:may|can|are subject to) change")
        c.fields["rate_type_note"] = ctx.field(var, var) if var else ctx.field(None, None)
        c.fields["min_balance_cents"] = X.min_amount(doc, ctx, "min_balance")
        self._deposit_fee_and_waivers(page, ctx, c)
        wr, wn = X.withdrawal_limit(doc, ctx)
        c.fields["withdrawal_restrictions"], c.fields["max_withdrawals_per_month"] = wr, wn
        c.fields["eligible_states"] = X.states(page.text, ctx)
        cr = X.first_line(doc, r"^(?:eligibility|who can open)\s*:")
        c.fields["customer_restrictions"] = (
            ctx.field(cr.split(":", 1)[1].strip(), cr)
            if cr
            else self._account_eligibility(ctx, self.deposit_lines(page))
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
            v = o.value if o is not None else None
            if v is None or (v.requirement_type is None and v.amount_qualifier != "tiered"):
                # the requirement or the tiers may be stated elsewhere on the page (spot-check findings 8, 10)
                ext = X.offer_context(page.text, b)
                if ext:
                    o2 = X.offer(
                        f"{b} {ext}",
                        foot,
                        ctx,
                        offer_type=offer_type,
                        offer_url=page.url,
                        tiers=tiers,
                        note=self.offer_note(page),
                        evidence=b,
                    )
                    v2 = o2.value if o2 is not None else None
                    if v2 is not None and (
                        v2.requirement_type is not None or v2.amount_qualifier == "tiered"
                    ):
                        o = o2
            if o is not None and o.value is not None and o.value.expiration_date is None:
                end = X.offer_end(page.text, b)
                if end is not None and ctx.locate(end[1]) is not None:
                    # keep the dated line with the offer so the date is visible in its verbatim text
                    v = o.value.model_copy(
                        update={
                            "expiration_date": end[0],
                            "verbatim_text": f"{o.value.verbatim_text} {end[1]}".strip(),
                        }
                    )
                    o = o.model_copy(update={"value": v})
            if (
                o is not None
                and o.value is not None
                and offer_type in ("checking_bonus", "savings_bonus")
                and o.value.eligibility_restrictions is None
                and (ex := D.bonus_eligibility(self.deposit_lines(page))) is not None
                and ctx.locate(ex) is not None
            ):
                # "You are not eligible for this Welcome Bonus if you have an existing Rewards Checking Account ..."
                o = o.model_copy(
                    update={"value": o.value.model_copy(update={"eligibility_restrictions": ex})}
                )
            if o is not None:
                c.offers.append(o)
        if offer_type in ("checking_bonus", "savings_bonus"):
            # the bonus terms restate the headline ("Earn a Welcome Bonus of $300 after you complete each of the
            # following qualifying criteria:"): the restatement without a requirement is the same offer
            full = {
                (o.value.amount_max, o.value.reward_unit)
                for o in c.offers
                if o.value is not None and o.value.requirement_type is not None
            }
            c.offers = [
                o
                for o in c.offers
                if o.value is None
                or o.value.requirement_type is not None
                or (o.value.amount_max, o.value.reward_unit) not in full
            ]
        # Offer capture (spot-check round 1): a page that shows an offer block (amount + spend + window) but yields no
        # offer is a reading failure, never "no offer". offer_status (round 2, D) records which case it is.
        bank = page.bank.display_name
        signal = X.offer_signal(page.doc.text if page.doc is not None else page.text)
        stated = X.no_offer_statement(page.doc.text if page.doc is not None else page.text)
        if c.offers:
            c.fields["offer_capture"] = ctx.field(True, c.offers[0].span_text, method="label_regex")
            c.offer_status = "captured"
        elif stated is not None and ctx.locate(stated) is not None:
            # The issuer says this card has no welcome offer ("won't be eligible for new cardmember bonus cash"):
            # a stated fact, not a capture gap.
            c.fields["offer_capture"] = ctx.field(True, stated, method="free_text")
            c.offer_status = "none_stated"
            c.offer_absent_note = f"No welcome offer (stated by {bank}): “{X.norm_ws(stated)}”"
            if re.search(r"\bintro(?:ductory)? APR\b", stated, re.IGNORECASE):
                for f in ("intro_purchase_apr_pct", "intro_purchase_apr_months"):
                    if not (cur := c.fields.get(f)) or not cur.present:
                        c.fields[f] = ctx.field(None, None, null_reason=NullReason.not_applicable)
        elif signal is not None:
            c.fields["offer_capture"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
            c.notes.append(f"offer block not read: {signal[:160]}")
            c.offer_status = "unreadable"
            c.offer_absent_note = (
                f"We couldn't read the welcome offer on this page. Check {bank} for the current offer."
            )
        elif self.rules.get("offers_script_only"):
            c.fields["offer_capture"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
            c.offer_status = "not_captured"
            c.offer_absent_note = (
                self.offer_absent_note(page)
                or f"Welcome offer not captured (shown only by the page script). Check {bank} for the current offer."
            )
        else:
            c.fields["offer_capture"] = ctx.field(None, None, null_reason=NullReason.not_applicable)
            c.offer_status = "none_found"
            c.offer_absent_note = self.offer_absent_note(page)
