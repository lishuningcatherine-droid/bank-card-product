"""American Express adapter (www.americanexpress.com/us/credit-cards/card/... pages).

Built from verbatim official pages captured on 2026-10-13 (``tests/fixtures/american_express/RETRIEVED.txt``);
pinned by value-asserting tests in ``tests/adapters/test_american_express.py``. See
``docs/adapters/american_express.md``. Behaviour follows brief §6.7:

* static pages carry the annual fee ("Annual Fee: ...") and the earn-rate tiles; the welcome offer and the APR appear
  only on the rendered page ("Welcome Offer & Key Details"), so sources are rendered;
* a welcome offer found on the rendered public page gets the note "Offers may vary; confirm on American Express at
  application"; when none is found, no offer record is created and the UI says "Check American Express for the
  current welcome offer";
* Rates & Fees and application pages under robots-disallowed paths (``/*/apply/``, ``/us/rwd/``) are never fetched.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter, lowest_rate_per_category
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, NullReason, Sourced
from bankrec.parsers.money import parse_fee_schedule

OFFER_NOTE = "Offers may vary; confirm on American Express at application"
OFFER_ABSENT = "Check American Express for the current welcome offer"
_FAQ_FEE_Q = re.compile(r"what is the annual fee|is there an annual fee|annual fee for the", re.IGNORECASE)
_SCOPE_LINES = 90  # the product's own hero, offer and earn tiles; cross-sell cards with their fees follow
_FEE = re.compile(r"^Annual Fee:\s*(.+?)[¤†\s]*(?:Explore)?$")
_APR = re.compile(
    r"(?:variable APR,? |\bAPR: )(\d{1,2}\.\d{2})% to (\d{1,2}\.\d{2})%(?: variable APR on purchases)?",
    re.IGNORECASE,
)
_INTRO = re.compile(
    r"(\d{1,2})% intro APR for (up to )?(\d{1,2}) months on purchases(?P<bt> and balance transfers)?", re.I
)
_TILE_RATE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?(?:%|X)$")
_OFFER_HEAD = re.compile(
    r"^(?:earn|get)\s+(?:up\s+to\s+|as\s+high\s+as\s+)?(?:\$[\d,]+|[\d,]{5,})\b", re.IGNORECASE
)


class Adapter(DeclarativeAdapter):
    bank_id = "american_express"
    parser_version = "american_express/1.0.0"

    def offer_note(self, page: ClassifiedPage) -> str | None:
        return OFFER_NOTE

    def offer_absent_note(self, page: ClassifiedPage) -> str | None:
        return OFFER_ABSENT

    def product_name(self, page: ClassifiedPage) -> str | None:
        """The product heading; on the static pages the only ``h1`` elements are modal titles ("All Dining and Grocery
        Benefits (4)"), so the page title ("The American Express® Gold Card") names the card instead."""
        doc = page.doc
        if doc is None:
            return None
        for n in doc.select("h1"):
            if n.attributes.get("id") == "modal-header" or re.search(r"\(\d+\)$", doc.node_text(n).strip()):
                continue
            t = doc.node_text(n).replace("\n", " ").strip()
            if t:
                return t
        title = re.sub(r"\s*[|–-]\s*American Express.*$", "", doc.title or "").strip()
        title = re.sub(r"^The\s+", "", title)
        return title if title and re.search(r"\bCard\b", title) and title in doc.text else None

    def _lines(self, page: ClassifiedPage) -> list[str]:
        doc = page.doc
        assert doc is not None
        lines = doc.text.split("\n")
        if doc.h1:
            idx = [i for i, ln in enumerate(lines) if ln == doc.h1[0]]
            # The name also appears in cross-sell lists; the product's own hero is followed by "Annual Fee:".
            hero = [i for i in idx if any(x.startswith("Annual Fee:") for x in lines[i : i + 6])]
            if hero or idx:
                start = (hero or idx)[0]
                return lines[start : start + _SCOPE_LINES]
        return lines[:_SCOPE_LINES]

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        out: dict[str, Sourced[Any]] = {}
        na = NullReason.not_applicable
        lines = self._lines(page)
        fee_line = next((ln for ln in lines if _FEE.match(ln)), None)
        if fee_line and (m := _FEE.match(fee_line)):
            value = m.group(1)
            sched = parse_fee_schedule(value)
            ongoing = 0 if re.fullmatch(r"no annual fee", value.strip(), re.I) else sched.ongoing_cents
            if ongoing is not None:
                out["annual_fee_cents"] = ctx.field(ongoing, fee_line, method="table_cell")
                if sched.intro_cents is not None and sched.intro_cents != ongoing:
                    out["intro_annual_fee_cents"] = ctx.field(
                        sched.intro_cents, fee_line, method="table_cell"
                    )
                    out["intro_annual_fee_months"] = ctx.field(
                        12 if sched.intro_text and "first year" in sched.intro_text else None, fee_line
                    )
                else:
                    out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
                    out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
        apr = next((ln for ln in lines if _APR.search(ln)), None)
        if apr and (m := _APR.search(apr)):
            out["purchase_apr_min_pct"] = ctx.field(Decimal(m.group(1)), apr, method="free_text")
            out["purchase_apr_max_pct"] = ctx.field(Decimal(m.group(2)), apr, method="free_text")
            out["purchase_apr_variable"] = ctx.field(True, apr, method="free_text")
            intro = _INTRO.search(apr)
            if intro and intro.group(2):
                # "0% intro APR for up to 18 months ... may be as short as 6 months": the duration is not fixed.
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
            elif intro:
                out["intro_purchase_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="free_text")
                out["intro_purchase_apr_months"] = ctx.field(int(intro.group(3)), apr, method="free_text")
                if intro.group("bt"):
                    out["intro_bt_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="free_text")
                    out["intro_bt_apr_months"] = ctx.field(int(intro.group(3)), apr, method="free_text")
            else:
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=na)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=na)
        ftf = next((ln for ln in lines if re.match(r"^no foreign transaction fees?\b", ln, re.I)), None)
        if ftf:
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), ftf, method="free_text")
        return out

    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        if page.doc is None:
            return []
        lines = self._lines(page)
        out: list[str] = []
        if key == "reward":
            # Tiles: "6%" / "CASH BACK" / "On Groceries" / "On up to $6,000 per year in purchases at U.S. supermarkets."
            for i, ln in enumerate(lines):
                if _TILE_RATE.match(ln) and i + 2 < len(lines):
                    unit, cat = lines[i + 1], lines[i + 2]
                    detail = lines[i + 3] if i + 3 < len(lines) and not _TILE_RATE.match(lines[i + 3]) else ""
                    if re.match(r"^\d{1,2}(?:\.\d+)?X\s+points?\b", cat, re.I):
                        out.append(
                            cat
                        )  # "2X / Points for Each Dollar / 2X points on all other eligible purchases."
                        continue
                    stmt = f"{ln} {unit} {cat}".rstrip("‡*")
                    if detail and not re.match(r"^(?:cash back is received|rewards|featured)", detail, re.I):
                        stmt = f"{stmt} {detail}"
                    if not re.search(r"\bup\s+to\s+\d|\btotal\b", f"{ln} {cat}", re.I):
                        out.append(stmt)
            # the base rate below the tiles: "Earn 1X Membership Rewards® points on all other eligible purchases.‡"
            base = r"^Earn\s+\d{1,2}(?:\.\d+)?X\b.*\bon all other eligible purchases"
            out += [ln for ln in lines if re.match(base, ln, re.I) and ln not in out]
            return out
        if key == "offer":
            for i, ln in enumerate(lines):
                if _OFFER_HEAD.search(ln):
                    nxt = lines[i + 1] if i + 1 < len(lines) else ""
                    block = f"{ln} {nxt}" if re.search(r"\bspend\b", nxt, re.I) else ln
                    if re.search(r"\bspend\s+\$[\d,]+", block, re.I):
                        return [block]
            return []
        if key in {"offer_footnote", "offer_tier", "credit", "benefit"}:
            return []
        return super().statements(page, key, fallback)

    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        if c.value("annual_fee_cents") is None:  # fee stated only in an FAQ answer (pre-survey note)
            lines = page.text.split("\n")
            for i, ln in enumerate(lines):
                if _FAQ_FEE_Q.search(ln) and i + 1 < len(lines):
                    answer = lines[i + 1]
                    sched = parse_fee_schedule(answer)
                    if sched.ongoing_cents is not None:
                        c.fields["annual_fee_cents"] = ctx.field(
                            sched.ongoing_cents, answer, method="label_regex", name="annual_fee_faq"
                        )
                        c.notes.append("annual fee taken from FAQ answer")
                    break
        # Cards issued by American Express run on its network; the page names it ("American Express ... Card").
        net = X.first_line(page.doc, r"\bAmerican Express\b.*\bCard\b") if page.doc is not None else None
        c.fields["network"] = ctx.field("American Express", net) if net else ctx.field(None, None)
        self.partner_rates(c)
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
