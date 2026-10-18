"""U.S. Bank adapter (www.usbank.com card pages).

Built from verbatim official pages captured on 2026-10-13 (``tests/fixtures/us_bank/RETRIEVED.txt``); pinned by
value-asserting tests in ``tests/adapters/test_us_bank.py``. See ``docs/adapters/us_bank.md``.

* Static HTML states the name, bonus and earn rates, but the annual fee and APR are bare "$" placeholders
  ("$ Annual fee", "a variable APR applies, currently $."). The page script fills them in, so sources are rendered.
* The product content is line-oriented: rate tiles ("5X points" + "on prepaid hotels ... booked directly in the
  Travel Center"), an offer headline and its requirement line, "$0 Annual fee", and "variable APR ..., currently
  17.99% - 28.24%".
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter, lowest_rate_per_category
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, NullReason, Sourced
from bankrec.parsers.money import parse_money

_SCOPE_LINES = 140  # product content follows the first h1; reviews, FAQs and the footer come later
_FEE = re.compile(r"^\$(\d[\d,]*) annual fee\b", re.IGNORECASE)
_NO_FEE = re.compile(r"\b(?:enjoy|with|and) (?:no|\$0) annual fee\b", re.IGNORECASE)
_INTRO_FEE = re.compile(
    r"^\$(\d+) intro annual fee for the first year, \$(\d[\d,]*) per year thereafter", re.I
)
_APR = re.compile(
    r"variable(?: APR)?(?: applies)?,? currently(?: ranging from)? (\d{1,2}\.\d{2})%(?:\s*-\s*(\d{1,2}\.\d{2})%)?",
    re.IGNORECASE,
)
_INTRO = re.compile(
    r"\b(\d{1,2})% intro APR\d*\s+(?:on|applies to) purchases(?P<bt>\s+and balance transfers)?\d*"
    r"(?:\s+for (?:the first )?(?P<n1>\d{1,2}) billing cycles|.{0,20}?After (?P<n2>\d{1,2}) billing cycles)",
    re.IGNORECASE,
)
_PLACEHOLDER_APR = re.compile(r"currently \$\s*\.?$|^\$ annual fee$", re.IGNORECASE)
_TILE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?\s*(?:x\s+points?|%\s+cash\s+back)\d?$", re.IGNORECASE)
_RATE_LEAD = re.compile(
    r"^(?:plus,?\s+)?(?:earn\s+)?(?:a\s+total\s+of\s+)?(?:unlimited\s+)?\d{1,2}(?:\.\d{1,2})?\s*(?:x\b|%)",
    re.IGNORECASE,
)
_NOT_EARN = re.compile(
    r"\bup\s+to\s+\d|\bsave\b|%\s+off\b|statement credit|\bbonus\b|\bAPR\b|respondents", re.IGNORECASE
)
_OFFER_HEAD = re.compile(
    r"^(?:earn|get)\s+(?:rewarded\s+with\s+)?(?:a\s+)?(?:\$[\d,]+|[\d,]{5,}\s+bonus\s+points)", re.IGNORECASE
)
_SPEND = re.compile(r"\bspend(?:ing)?\s+\$[\d,]+", re.IGNORECASE)


class Adapter(DeclarativeAdapter):
    bank_id = "us_bank"
    parser_version = "us_bank/1.0.0"

    def _lines(self, page: ClassifiedPage) -> list[str]:
        doc = page.doc
        assert doc is not None
        lines = doc.text.split("\n")
        if doc.h1:
            for i, ln in enumerate(lines):
                if ln == doc.h1[0]:
                    return lines[i : i + _SCOPE_LINES]
        return lines[:_SCOPE_LINES]

    def product_name(self, page: ClassifiedPage) -> str | None:
        doc = page.doc
        if doc is None or not doc.h1:
            return None
        h = doc.h1[0].strip()
        if h.isupper():  # "U.S. BANK CASH+® VISA SIGNATURE® CARD": prefer the page's own mixed-case spelling
            for ln in doc.text.split("\n"):
                if ln.strip().lower() == h.lower() and not ln.strip().isupper():
                    return ln.strip()
        return h

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        out: dict[str, Sourced[Any]] = {}
        na = NullReason.not_applicable
        lines = self._lines(page)
        fee = next((ln for ln in lines if _FEE.search(ln)), None)
        intro_fee = next((ln for ln in lines if _INTRO_FEE.search(ln)), None)
        if intro_fee and (m := _INTRO_FEE.search(intro_fee)):
            out["annual_fee_cents"] = ctx.field(int(m.group(2).replace(",", "")) * 100, intro_fee)
            out["intro_annual_fee_cents"] = ctx.field(int(m.group(1)) * 100, intro_fee)
            out["intro_annual_fee_months"] = ctx.field(12, intro_fee)
        elif fee and (m := _FEE.search(fee)):
            out["annual_fee_cents"] = ctx.field(
                int(m.group(1).replace(",", "")) * 100, fee, method="label_regex"
            )
        elif no_fee := next((ln for ln in lines if _NO_FEE.search(ln)), None):
            # An anchored "no annual fee" / "$0 annual fee" phrase is a labelled statement (DESIGN §24.9).
            out["annual_fee_cents"] = ctx.field(0, no_fee, method="label_regex")
        elif any(_PLACEHOLDER_APR.search(ln) for ln in lines):
            out["annual_fee_cents"] = ctx.field(None, None, null_reason=NullReason.requires_render)
        if "annual_fee_cents" in out and "intro_annual_fee_cents" not in out:
            out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
            out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
        apr = next((ln for ln in lines if _APR.search(ln)), None)
        if apr and (m := _APR.search(apr)):
            lo = Decimal(m.group(1))
            hi = Decimal(m.group(2)) if m.group(2) else lo
            out["purchase_apr_min_pct"] = ctx.field(lo, apr, method="free_text")
            out["purchase_apr_max_pct"] = ctx.field(hi, apr, method="free_text")
            out["purchase_apr_variable"] = ctx.field(True, apr, method="free_text")
            intro = _INTRO.search(apr)
            if intro and (n := intro.group("n1") or intro.group("n2")):
                out["intro_purchase_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="free_text")
                out["intro_purchase_apr_months"] = ctx.field(int(n), apr, method="free_text")
                if intro.group("bt"):
                    out["intro_bt_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="free_text")
                    out["intro_bt_apr_months"] = ctx.field(int(n), apr, method="free_text")
            else:
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=na)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=na)
        elif any(re.search(r"currently \$\s*\.?$", ln, re.I) for ln in lines):
            out["purchase_apr_min_pct"] = ctx.field(None, None, null_reason=NullReason.requires_render)
            out["purchase_apr_max_pct"] = ctx.field(None, None, null_reason=NullReason.requires_render)
        ftf = next((ln for ln in lines if re.match(r"^no foreign transaction fees?\b", ln, re.I)), None)
        if ftf:
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), ftf, method="free_text")
        dep = next((ln for ln in lines if re.search(r"security deposit of \$\d", ln, re.I)), None)
        if dep and (m := re.search(r"security deposit of (\$[\d,]+)", dep, re.I)):
            amt = parse_money(m.group(1))
            if amt is not None:
                out["secured_min_deposit_cents"] = ctx.field(amt, dep, method="free_text")
        return out

    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        if page.doc is None:
            return []
        lines = self._lines(page)
        out: list[str] = []
        if key == "reward":
            joined: list[str] = []
            for i, ln in enumerate(lines):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                # A rate followed by "On air, hotel and car reservations booked directly in the Travel Center"
                # belongs to the portal: keep the two lines together so the portal wording is seen.
                if _RATE_LEAD.search(ln) and re.search(r"\bTravel Center\b", nxt):
                    joined.append(f"{ln} {nxt}")
                elif _TILE.match(ln) and nxt[:1].islower():
                    joined.append(
                        f"{re.sub(r'\\d$', '', ln)} {nxt}"
                    )  # "5X points2" + "on prepaid hotels ..."
                else:
                    joined.append(ln)
            for ln in joined:
                for clause in X.split_rate_clauses(ln):
                    clause = re.sub(r"^(?:and|plus)\s+", "", clause.strip(), flags=re.I)
                    if not re.search(r"\bTravel Center\b", clause):
                        # One sentence per rate: "1X point on all other purchases. Plus, a $15 streaming credit"
                        clause = re.split(r"(?<=[a-z*])\.\s+", clause)[0]
                    if _RATE_LEAD.search(clause) and not _NOT_EARN.search(clause) and clause not in out:
                        out.append(clause)
            return out
        if key == "offer":
            for i, ln in enumerate(lines):
                if _OFFER_HEAD.search(ln):
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    # a headline without its requirement is still returned: the shared offer step looks for the
                    # requirement elsewhere on the page (e.g. a footnote; spot-check finding 8)
                    return [ln if _SPEND.search(ln) else f"{ln} {nxt}" if _SPEND.search(nxt) else ln]
            return []
        if key == "credit":
            # recurring benefits: "Earn a $20 annual statement credit for 11 consecutive months of purchases.4"
            return [
                ln
                for ln in lines
                if re.match(r"^Earn an?\s+\$\d[\d,]*\s+(?:annual|yearly)\s+statement credit\b", ln)
            ]
        if key in {"offer_footnote", "offer_tier", "benefit"}:
            return []
        return super().statements(page, key, fallback)

    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        name = c.name or ""
        if urlsplit(page.url).path.startswith("/business-banking/"):
            c.fields["segment"] = ctx.field("business", name)  # every business card name says "Business"
        c.fields["network"] = (
            ctx.field("Visa", name) if re.search(r"\bVisa\b", name) else ctx.field(None, None)
        )
        c.reward_rates = lowest_rate_per_category(c.reward_rates)
        base = [r for r in c.reward_rates if r.value and r.value.category == "other"]
        c.fields["base_rate"] = (
            ctx.field(base[0].value.rate, base[0].span_text)
            if base and base[0].value
            else ctx.field(None, None)
        )
        cur, _ = X.reward_currency(c.reward_rates, " ".join(r.span_text or "" for r in c.reward_rates))
        c.fields["reward_currency"] = (
            ctx.field(cur, c.reward_rates[0].span_text) if cur and c.reward_rates else ctx.field(None, None)
        )
