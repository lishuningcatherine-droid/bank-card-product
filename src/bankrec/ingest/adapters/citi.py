"""Citi adapter (www.citi.com/credit-cards/... card pages, rendered).

Built from verbatim rendered pages captured on 2026-11-09 (``tests/fixtures/citi/RETRIEVED.txt``); pinned by
``tests/adapters/test_citi.py``. See ``docs/adapters/citi.md``.

* The static HTML states the offer without its numbers ("Earn bonus points after spending $ in the first months");
  the rendered page fills them in ("Earn 60,000 bonus points" / "after spending $4,000 in the first 3 months2").
* Earn rates are tiles whose second line is the full statement ("10 points per dollar spent on Hotels, Car Rentals
  and Attractions booked on cititravel.com2"); the trailing digit is a footnote marker.
* The offer's channel and eligibility notice follows the hero ("This offer may not be available if you leave this
  page. ... New account bonus offer is not available if you currently have or previously had ...").
* Double Cash states its rate as "Unlimited 2% cash back on purchases" (1% when you buy, 1% as you pay); it is read
  as the card's rate on all purchases.
* A page saying Citi "is no longer accepting applications" for the card (Custom Cash, 2026-05-28) yields no offer.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter
from bankrec.ingest.common import cards as K
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, RewardRateRec, Sourced

_HERO = re.compile(
    r"^Earn (?:[\d,]+ (?:AAdvantage® )?bonus (?:points|miles)|\$[\d,]+ cash back bonus)$", re.I
)
_HERO_REQ = re.compile(r"^(?:after spending|For your business after) \$[\d,]+", re.I)
_FEE_WAIVED = re.compile(r"^Annual Fee, waived for the first year\d?$", re.I)
_TERMS = re.compile(r"^This offer may not be available if you leave this page\.", re.I)
_ELIGIBILITY = re.compile(
    r"(?:New account bonus offer|Bonus ThankYou® Points) (?:is |are )?not available", re.I
)
_POINTS = re.compile(r"^\d{1,2} points? per dollar spent (?:on|at) ", re.I)
# "Earn 2 AAdvantage® miles for your business on every $1 spent at car rental merchants and gas stations2"
_MILES = re.compile(
    r"^Earn (\d{1,2}) AAdvantage® miles? for your business on every \$1 spent (?:on|at) (.+)$", re.I
)
_DOUBLE = re.compile(r"^Unlimited (\d)% cash back on purchases$", re.I)


class Adapter(DeclarativeAdapter):
    bank_id = "citi"
    parser_version = "citi/1.0.0"

    def product_name(self, page: ClassifiedPage) -> str | None:
        expected = page.source.expected_entity
        if page.doc is not None and expected.lower() in X.norm_ws(page.doc.text).lower():
            return expected
        return super().product_name(page)

    @staticmethod
    def _lines(page: ClassifiedPage) -> list[str]:
        assert page.doc is not None
        return [ln.strip() for ln in page.doc.text.split("\n") if ln.strip()]

    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        if page.doc is None:
            return []
        lines = self._lines(page)
        if key == "offer":
            out = []
            for i, ln in enumerate(lines[:-1]):
                nxt = lines[i + 1]
                if _HERO.match(ln) and _HERO_REQ.match(nxt):
                    # "Earn 75,000 AAdvantage® bonus miles" / "For your business after $5,000 in purchases ..."
                    out.append(f"{ln} {K.strip_footnote(nxt)}")
            return out[:1]
        if key == "offer_footnote":
            # the notice's eligibility sentences only: its "Offers may vary" is about channels, not the amount
            out = []
            for ln in lines:
                if _TERMS.match(ln) and (m := _ELIGIBILITY.search(ln)):
                    out.append(ln[m.start() :].strip())
            return out[:1]
        if key == "reward":
            return [K.strip_footnote(ln) for ln in lines if _POINTS.match(ln)]
        if key in ("credit", "benefit", "offer_tier"):
            return []
        return super().statements(page, key, fallback)

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        out = super().fees_and_rates(page, ctx)
        lines = self._lines(page)
        for i, ln in enumerate(lines[:-1]):
            nxt = lines[i + 1]
            # hero: "$99" / "Annual Fee, waived for the first year1"
            if re.fullmatch(r"\$\d[\d,]*", ln) and _FEE_WAIVED.match(nxt):
                ev = f"{ln} {K.strip_footnote(nxt)}"
                out["annual_fee_cents"] = ctx.field(
                    int(ln[1:].replace(",", "")) * 100, ev, method="table_cell"
                )
                out["intro_annual_fee_cents"] = ctx.field(0, ev, method="table_cell")
                out["intro_annual_fee_months"] = ctx.field(12, ev, method="table_cell")
                break
            # "Annual Fee1" / "$95" (the pricing box)
            if re.fullmatch(r"Annual Fee\d?", ln) and re.fullmatch(r"\$\d[\d,]*", nxt):
                out["annual_fee_cents"] = ctx.field(
                    int(nxt[1:].replace(",", "")) * 100, f"{ln} {nxt}", method="table_cell", name="annual_fee"
                )
                break
        for i, ln in enumerate(lines[:-1]):
            m = re.fullmatch(r"(\d{1,2}\.\d{2})% - (\d{1,2}\.\d{2})%", lines[i + 1])
            # the box is the purchase APR only when it says so ("on purchases and balance transfers ...");
            # Double Cash's box is for balance transfers
            if (
                re.fullmatch(r"Variable APR\d?", ln)
                and m
                and lines[i + 2 : i + 3]
                and "purchases" in lines[i + 2]
            ):
                ev = f"{ln} {lines[i + 1]} {lines[i + 2]}"
                out["purchase_apr_min_pct"] = ctx.field(Decimal(m.group(1)), ev, method="table_cell")
                out["purchase_apr_max_pct"] = ctx.field(Decimal(m.group(2)), ev, method="table_cell")
                out["purchase_apr_variable"] = ctx.field(True, ev, method="table_cell")
                break
        ftf = next((ln for ln in lines if re.fullmatch(r"No foreign transaction fees\d?", ln, re.I)), None)
        if ftf:
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), K.strip_footnote(ftf), method="label_regex")
        return out

    def _offers(
        self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate, offer_type: str
    ) -> None:
        super()._offers(page, ctx, c, offer_type)
        blocks = self.statements(page, "offer", None)
        if not blocks or "AAdvantage® bonus miles" not in blocks[0]:
            return
        # The shared offer reader knows "75,000 bonus miles", not "75,000 AAdvantage® bonus miles ... For your
        # business after $5,000": it reads the same words without the program name and the business phrase, with
        # the page's hero as the located evidence.
        plain = re.sub(
            r"AAdvantage® bonus miles\s+For your business after", "bonus miles after spending", blocks[0]
        )
        foot = " ".join(self.statements(page, "offer_footnote", None))
        o = X.offer(plain, foot, ctx, offer_type=offer_type, offer_url=page.url, evidence=blocks[0])
        if o is not None and o.value is not None and o.value.requirement_type is not None:
            v = o.value.model_copy(update={"verbatim_text": blocks[0], "channel": self._channel(page)})
            c.offers = [o.model_copy(update={"value": v})]

    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        if page.doc is None:
            return
        miles = [(m, ln) for ln in self._lines(page) if (m := _MILES.match(K.strip_footnote(ln)))]
        if miles and not c.reward_rates:
            from bankrec.normalize.categories import categories_in

            rates = []
            for m, ln in miles:
                where = m.group(2)
                cats = (
                    ["partner"]
                    if re.search(r"\bAmerican Airlines\b", where)
                    else [x for x in categories_in(where) if x != "other"] or categories_in(where)
                )
                for cat in cats:
                    rec = RewardRateRec(
                        category=cat, rate=Decimal(m.group(1)), rate_unit="x", text=K.strip_footnote(ln)
                    )
                    rates.append(
                        ctx.field(rec, K.strip_footnote(ln), method="free_text", name=f"reward:{cat}")
                    )
            done = all(categories_in(m.group(2)) or "American Airlines" in m.group(2) for m, _ in miles)
            c.reward_rates = [r for r in rates if r.present]
            base = [r for r in c.reward_rates if r.value and r.value.category == "other"]
            if base and base[0].value:
                c.fields["base_rate"] = ctx.field(base[0].value.rate, base[0].span_text, method="free_text")
            if c.reward_rates:
                c.fields["reward_currency"] = ctx.field(
                    "miles", c.reward_rates[0].span_text, method="free_text"
                )
            if not done:
                from bankrec.model import NullReason

                c.fields["earn_rates_complete"] = ctx.field(None, None, null_reason=NullReason.ambiguous)
            return
        if c.reward_rates:
            return
        line = next((ln for ln in self._lines(page) if _DOUBLE.match(ln)), None)
        if line is None:
            return
        m = _DOUBLE.match(line)
        assert m is not None
        rec = RewardRateRec(category="other", rate=Decimal(m.group(1)), rate_unit="pct", text=line)
        rate = ctx.field(rec, line, method="label_regex", name="reward:other")
        if rate.present:
            c.reward_rates = [rate]
            c.fields["base_rate"] = ctx.field(rec.rate, line, method="label_regex")
            c.fields["reward_currency"] = ctx.field("cashback", line, method="label_regex")
            c.fields["earn_rates_complete"] = ctx.field(True, line, method="label_regex")
