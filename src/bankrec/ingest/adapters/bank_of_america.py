"""Bank of America adapter (www.bankofamerica.com card pages).

Built from verbatim official pages captured on 2026-10-13 (``tests/fixtures/bank_of_america/RETRIEVED.txt``); pinned
by value-asserting tests in ``tests/adapters/test_bank_of_america.py``. See ``docs/adapters/bank_of_america.md``.

* The **static HTML holds no product details**: only the page shell, the site navigation and the visible message
  "We're sorry, this page is temporarily unavailable" (configured as boilerplate). The card content is inserted by
  the page script, so every source is rendered (``requires_render``).
* Rendered pages state the pricing summary as ``.rates-table-body .table-cols`` blocks (an ``h3`` label —
  "Introductory APR", "Standard APR", "Annual Fee", "Balance Transfer Fee" — and its value), and the card details
  as ``.card-details-cc-module .feature-content`` blocks (an ``h3`` title and a paragraph).
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import Any

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter, lowest_rate_per_category
from bankrec.ingest.common import extract as X
from bankrec.model import ExtractionContext, NullReason, PageType, Sourced
from bankrec.normalize.categories import categories_in
from bankrec.parsers.money import parse_fee_schedule, parse_money

_RANGE = re.compile(r"(\d{1,2}\.\d{2})%\s*(?:–|-|to)\s*(\d{1,2}\.\d{2})%")
_SINGLE = re.compile(r"(\d{1,2}\.\d{2})%\s+variable", re.IGNORECASE)
_INTRO = re.compile(
    r"(\d{1,2}(?:\.\d+)?)% for (\d{1,2}) billing cycles(?P<rest>.*)", re.IGNORECASE
)  # "0% for 15 billing cycles Applies to purchases, and to any balance transfers made within 60 days ..."
_RATE_LEAD = re.compile(
    r"^(?:automatic\s+)?(?:plus,\s+)?(?:earn\s+)?(?:unlimited\s+)?\d{1,2}(?:\.\d{1,2})?\s*(?:%|x\b|"
    r"\s+(?:[A-Z][A-Za-z]*®?\s+)?(?:points?|miles?)\s+(?:per|for\s+(?:each|every)))",
    re.IGNORECASE,
)
_NOT_EARN = re.compile(
    r"\bup\s+to\s+\d|\bsave\b|%\s+off\b|\bdiscount|\binflight\b|\b\d+%\s+back\s+on\b|first-year|bonus\b|"
    r"category of your choice|\brewards bonus\b",
    re.IGNORECASE,
)
# "Earn 6% and 2% cash back on the first $2,500 in combined purchases each quarter in the choice category, and at
# grocery stores and wholesale clubs": one quarterly cap shared by the choice category and the grocery rate.
# Rewards-tab lines: "Automatic 2% ...", "Unlimited 1% ...", "Plus, earn 1.5 Miles for every $1 ...",
# "Earn 1 WorldPoints® point per $1 ...", "1 point per dollar spent on all other purchases".
_EXTRA_EARN = re.compile(
    r"^(?:(?:automatic|unlimited)\s+\d|(?:plus,\s+)?earn\s+(?:unlimited\s+)?\d|\d{1,2}(?:\.\d+)?\s+(?:points?|miles?)\s+(?:per|for)\b)",
    re.IGNORECASE,
)
_PLUS_FIRST_YEAR = re.compile(
    r"\d%[^%]{0,20}\+\s*\d+%\s+first-year[^.]*\bcategory of your choice", re.IGNORECASE
)
_RESPECTIVELY = re.compile(r"\d+(?:\.\d+)?%\s+and\s+\d+(?:\.\d+)?%")
_SHARED_CAP = re.compile(r"on the first \$([\d,]+) in combined purchases each (quarter|year)", re.IGNORECASE)
_OFFER_REQ = re.compile(r"\b(?:make|making|spend|spending)\s+(?:at\s+least\s+)?\$[\d,]+", re.IGNORECASE)
_OFFER_AMT = re.compile(
    r"\$[\d,]+\s+(?:online\s+)?cash\s+rewards\s+bonus|[\d,]{5,}\s+(?:online\s+)?bonus\s+(?:points|miles)",
    re.I,
)


_TERMS_H1 = re.compile(r"^Terms and Conditions for (.+)$")


def _after(lines: list[str], label: str, stop: tuple[str, ...]) -> list[str]:
    """Lines after an exact label line, up to the next line starting with one of ``stop``."""
    try:
        i = lines.index(label)
    except ValueError:
        return []
    out = []
    for ln in lines[i + 1 :]:
        if ln.startswith(stop):
            break
        out.append(ln)
    return out


class Adapter(DeclarativeAdapter):
    bank_id = "bank_of_america"
    parser_version = "bank_of_america/1.1.1"

    _account: str | None = None

    def extract(self, page: ClassifiedPage) -> list[ProductCandidate]:
        """The Advantage Banking page lists several checking accounts (``multi_account_pages`` in the rules): one
        candidate per account, each read only from that account's own fee and waiver block (DESIGN §24.21)."""
        accounts = (self.rules.get("multi_account_pages") or {}).get(page.source.slug)
        if not accounts:
            return super().extract(page)
        out: list[ProductCandidate] = []
        try:
            for name in accounts:
                self._account = name
                one = replace(page, source=page.source.model_copy(update={"expected_entity": name}))
                out += super().extract(one)
        finally:
            self._account = None
        return out

    def page_is_scoped(self, page: ClassifiedPage) -> bool:
        return self._account is not None

    def deposit_lines(self, page: ClassifiedPage) -> list[str]:
        lines = super().deposit_lines(page)
        if self._account is None:
            return lines
        accounts = (self.rules.get("multi_account_pages") or {}).get(page.source.slug) or []
        starts = [
            k
            for k, ln in enumerate(lines[:-1])
            if ln.strip() in accounts and re.match(r"^\$[\d.]+ or \$0$", lines[k + 1].strip())
        ]
        mine = [k for k in starts if lines[k].strip() == self._account]
        if not mine:
            return []
        a = mine[-1]  # the detailed "Monthly maintenance fee" block, after the summary tiles
        later = [k for k in starts if k > a]
        return lines[a : later[0] if later else a + 14]

    @staticmethod
    def _is_terms(page: ClassifiedPage) -> bool:
        return page.page_type is PageType.terms_page

    def product_name(self, page: ClassifiedPage) -> str | None:
        if page.doc is not None and self._is_terms(page):
            # "Terms and Conditions for Bank of America® Unlimited Cash Rewards" → the same canonical product
            for h in page.doc.h1:
                if m := _TERMS_H1.match(h.strip()):
                    return m.group(1).strip()
            return None
        return super().product_name(page)

    def _terms_fees(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        """The Schumer box of the rendered terms page (label line, then value lines)."""
        assert page.doc is not None
        lines = page.doc.text.split("\n")
        out: dict[str, Sourced[Any]] = {}
        na = NullReason.not_applicable
        fee = _after(lines, "Annual Fee", ("Transaction Fees", "Penalty", "•"))
        # The value is the line that is only an amount or "None" (a "NOTICE: ..." paragraph may come first).
        val = next(
            (ln for ln in fee if re.fullmatch(r"(?:\$\d[\d,]*(?:\.\d{2})?|none)\.?", ln.strip(), re.I)), None
        )
        if val is not None:
            v = val
            cents = 0 if re.fullmatch(r"none\.?", v.strip(), re.I) else parse_money(v)
            if cents is not None and not re.search(r"\bintro|first year\b", " ".join(fee), re.I):
                out["annual_fee_cents"] = ctx.field(cents, v, method="table_cell")
                out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
                out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
        pur = _after(lines, "Annual Percentage Rate (APR) for Purchases", ("APR for Balance Transfers",))
        for ln in pur:
            if m := _RANGE.search(ln) or re.search(r"(\d{1,2}\.\d{2})%,? based on", ln):
                lo = Decimal(m.group(1))
                hi = Decimal(m.group(2)) if m.re is _RANGE else lo
                out["purchase_apr_min_pct"] = ctx.field(lo, ln, method="table_cell")
                out["purchase_apr_max_pct"] = ctx.field(hi, ln, method="table_cell")
                out["purchase_apr_variable"] = ctx.field(
                    bool(re.search(r"vary with the market", " ".join(pur), re.I)), ln, method="table_cell"
                )
                break
        ftf = _after(lines, "• Foreign Transaction", ("Penalty Fee", "•"))
        if ftf:
            v = ftf[0]
            if re.match(r"^none\b", v, re.I):
                out["foreign_tx_fee_pct"] = ctx.field(
                    Decimal("0"), f"• Foreign Transaction\n{v}", method="table_cell"
                )
            elif m := re.match(r"^(\d{1,2}(?:\.\d+)?)% of the U\.S\. dollar amount", v):
                out["foreign_tx_fee_pct"] = ctx.field(
                    Decimal(m.group(1)), f"• Foreign Transaction\n{v}", method="table_cell"
                )
        bt = _after(lines, "• Balance Transfer", ("•", "Penalty Fee"))
        pcts = [m for ln in bt if (m := re.match(r"^(\d{1,2})% of the amount of each transaction", ln))]
        if pcts:  # the last stated fee is the ongoing one ("After that, your fee will be: 5% ...")
            out["bt_fee_pct"] = ctx.field(Decimal(pcts[-1].group(1)), pcts[-1].string, method="table_cell")
        return out

    # ------------------------------------------------------------------ blocks
    def _rates_table(self, page: ClassifiedPage) -> dict[str, tuple[str, str]]:
        """{label: (value text, evidence "label value")} from the Interest Rates & Fees Summary."""
        doc = page.doc
        assert doc is not None
        out: dict[str, tuple[str, str]] = {}
        for n in doc.select(".rates-table-body .table-cols"):
            h = n.css_first("h3")
            if h is None:
                continue
            label = re.sub(r"\s+", " ", doc.node_text(h)).strip()
            full = re.sub(r"\s+", " ", doc.node_text(n)).strip()
            value = full[len(label) :].strip() if full.startswith(label) else full
            out.setdefault(label.lower(), (value, full))
        return out

    def _features(self, page: ClassifiedPage) -> list[tuple[str, str]]:
        doc = page.doc
        assert doc is not None
        out = []
        for n in doc.select(".card-details-cc-module .feature-content"):
            h, p = n.css_first("h3"), n.css_first("p")
            ht = re.sub(r"\s+", " ", doc.node_text(h)).strip() if h is not None else ""
            pt = re.sub(r"\s+", " ", doc.node_text(p)).strip() if p is not None else ""
            out.append((ht, pt))
        return out

    # ------------------------------------------------------------------ fees and APR
    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        if self._is_terms(page):
            return self._terms_fees(page, ctx)
        out: dict[str, Sourced[Any]] = {}
        na = NullReason.not_applicable
        table = self._rates_table(page)
        if "annual fee" in table:
            value, ev = table["annual fee"]
            sched = parse_fee_schedule(value)
            out["annual_fee_cents"] = (
                ctx.field(sched.ongoing_cents, ev, method="table_cell")
                if sched.ongoing_cents is not None
                else X.placeholder_or_missing(ctx, value)
            )
            out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
            out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
        if "standard apr" in table:
            value, ev = table["standard apr"]
            rng, single = _RANGE.search(value), _SINGLE.search(value)
            lo: Decimal | None
            hi: Decimal | None
            if rng:
                lo, hi = Decimal(rng.group(1)), Decimal(rng.group(2))
            elif single:
                lo = hi = Decimal(single.group(1))
            else:
                lo = hi = None
            if lo is not None:
                out["purchase_apr_min_pct"] = ctx.field(lo, ev, method="table_cell")
                out["purchase_apr_max_pct"] = ctx.field(hi, ev, method="table_cell")
                out["purchase_apr_variable"] = ctx.field(
                    bool(re.search(r"\bvariable\b", value, re.I)), ev, method="table_cell"
                )
            else:
                out["purchase_apr_min_pct"] = X.placeholder_or_missing(ctx, value)
                out["purchase_apr_max_pct"] = X.placeholder_or_missing(ctx, value)
        if "introductory apr" in table:
            value, ev = table["introductory apr"]
            m = _INTRO.search(value)
            if m and re.search(r"\bpurchases\b", m.group("rest"), re.I):
                # Billing cycles are monthly; the count is stored as months and the evidence keeps the wording.
                out["intro_purchase_apr_pct"] = ctx.field(Decimal(m.group(1)), ev, method="table_cell")
                out["intro_purchase_apr_months"] = ctx.field(int(m.group(2)), ev, method="table_cell")
                if re.search(r"\bbalance transfers\b", m.group("rest"), re.I):
                    out["intro_bt_apr_pct"] = ctx.field(Decimal(m.group(1)), ev, method="table_cell")
                    out["intro_bt_apr_months"] = ctx.field(int(m.group(2)), ev, method="table_cell")
            elif re.fullmatch(r"none", value.strip(), re.I):
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=na)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=na)
        if "balance transfer fee" in table:
            value, ev = table["balance transfer fee"]
            # "5% of each transaction"; with an intro fee the ongoing one is "the fee for all future balance
            # transfers is 5%".
            m = re.search(r"future balance transfers is (\d{1,2})%", value) or re.match(
                r"(\d{1,2})% of each transaction\W*$", value
            )
            if m:
                out["bt_fee_pct"] = ctx.field(Decimal(m.group(1)), ev, method="table_cell")
        for head, body in self._features(page):
            text = f"{head} {body}"
            if "foreign_tx_fee_pct" not in out and re.search(
                r"\bno foreign transaction fees?\b|without incurring foreign transaction fees", text, re.I
            ):
                out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), text, method="free_text")
            if re.search(r"minimum security deposit", head, re.I) and (amt := parse_money(head)) is not None:
                out["secured_min_deposit_cents"] = ctx.field(amt, head, method="free_text")
        return out

    # ------------------------------------------------------------------ statements
    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        if page.doc is None:
            return []
        if self._is_terms(page) and key in {
            "reward",
            "offer",
            "offer_footnote",
            "offer_tier",
            "credit",
            "benefit",
        }:
            return []  # rewards and offers come from the product page only
        feats = self._features(page)
        if key == "reward":
            out: list[str] = []
            # Card-detail paragraphs, plus the rewards tab's one-line statements ("Automatic 2% cash back at grocery
            # stores and wholesale clubs", "Unlimited 1% cash back on all other purchases").
            lines = [b for _, b in feats] + [ln for ln in page.doc.text.split("\n") if _EXTRA_EARN.match(ln)]
            for body in lines:
                if _RESPECTIVELY.search(body):
                    continue  # "6% and 2% ... in the choice category, and at grocery stores": pairing is ambiguous
                # one sentence at a time: "... on all other purchases. Plus, earn a 10% rewards bonus ..."
                sentences = re.split(r"(?<=[a-z*®])\.\s+(?=[A-Z])", body)
                for clause in (
                    c
                    for sent in sentences
                    # "3% cash back + 3% first-year cash back bonus in the category of your choice" stays whole: the
                    # parser counts the ongoing 3% for the category after the added first-year bonus.
                    for c in ([sent] if _PLUS_FIRST_YEAR.search(sent) else X.split_rate_clauses(sent))
                ):
                    clause = re.sub(r"^(?:and|plus)\s+(?:unlimited\s+)?", "", clause, flags=re.I)
                    excluded = _NOT_EARN.search(clause) and not _PLUS_FIRST_YEAR.search(clause)
                    if _RATE_LEAD.search(clause) and not excluded and clause not in out:
                        out.append(clause)
            return out
        if key == "offer":
            offers = []
            for head, body in feats:
                if (
                    re.search(r"\boffer\b|\bbonus\b", head, re.I)
                    and _OFFER_REQ.search(body)
                    and _OFFER_AMT.search(body)
                ):
                    offers.append(body)
            return offers[:1]
        if key in {"offer_footnote", "offer_tier", "credit", "benefit"}:
            return []
        return super().statements(page, key, fallback)

    # ------------------------------------------------------------------ extras
    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        name = c.name or ""
        for net, pat in (("Visa", r"\bVisa\b"), ("Mastercard", r"\bMaster[Cc]ard\b")):
            if re.search(pat, name):
                c.fields["network"] = ctx.field(net, name)
                break
        else:
            c.fields["network"] = ctx.field(None, None)
        self.partner_rates(c)
        shared = next((m for ln in page.text.split("\n") if (m := _SHARED_CAP.search(ln))), None)
        if shared is not None:
            line = shared.string
            capped = []
            for r in c.reward_rates:
                v = r.value
                if v is not None and v.category != "other" and v.cap_cents is None:
                    if v.category not in categories_in(line[shared.end() :]):
                        continue  # a bonus rate the shared cap sentence does not cover: cap unknown, left out
                    r = r.model_copy(
                        update={
                            "value": v.model_copy(
                                update={
                                    "cap_cents": int(shared.group(1).replace(",", "")) * 100,
                                    "cap_period": "quarterly"
                                    if shared.group(2).lower() == "quarter"
                                    else "annual",
                                    "cap_combined": True,
                                }
                            )
                        }
                    )
                capped.append(r)
            c.reward_rates = capped
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
