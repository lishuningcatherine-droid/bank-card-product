"""Capital One adapter (www.capitalone.com card pages).

Built from verbatim official pages retrieved on 2026-10-13 (``tests/fixtures/capital_one/RETRIEVED.txt``); pinned
by value-asserting tests in ``tests/adapters/test_capital_one.py``. See ``docs/adapters/capital_one.md``.

* Consumer card pages state their facts as "showcase" pairs: an ``h3.showcase-headline`` ("Annual Fee", "Purchase
  Rate", "Credit Level", "10X", "New Cardmember Offer") and a ``.showcase-body`` ("$395", "19.74% - 28.74% variable
  APR", ...). Small-business pages state them as plain lines ("$395 annual fee", "24.74% variable APR.").
* Pages are static HTML. Rendering them is not possible within robots.txt: the page script loads its card data from
  ``card-apis.capitalone.com`` (robots.txt answers 403 → treated as disallow-all), and without it the app redirects
  to ``/page-not-found/``. Sources are therefore fetched with plain HTTP, and offers stated in the static HTML are
  captured from it (DESIGN §24.6).
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
from bankrec.parsers.money import parse_fee_schedule, parse_money

_RANGE = re.compile(r"(\d{1,2}\.\d{2})%\s*(?:–|-|to)\s*(\d{1,2}\.\d{2})%")
_SINGLE = re.compile(r"(\d{1,2}\.\d{2})%\s+variable APR", re.IGNORECASE)
_INTRO = re.compile(
    r"(\d{1,2}(?:\.\d+)?)% intro APR for (\d{1,2}) months on purchases(?P<bt> and balance transfers)?",
    re.IGNORECASE,
)
_RATE_HEAD = re.compile(
    r"^(?:earn\s+|unlimited\s+)?\d{1,2}(?:\.\d{1,2})?\s*(?:x\b|%)", re.IGNORECASE
)  # "10X", "Earn 5% cash back", "Unlimited 2X miles", "5% in card rewards"
_EARN_LINE = re.compile(
    r"^(?:earn|get)\s+(?:unlimited\s+)?\d{1,2}(?:\.\d{1,2})?\s*(?:%|x\b|\s+miles?\s+per)"
    # "Book through Capital One Business Travel to earn 10X miles on hotels and rental cars, and 5X miles on ..."
    r"|^book\s+through\s+[^.]{0,60}?\bto\s+earn\s+\d",
    re.IGNORECASE,
)
_NOT_EARN = re.compile(
    r"\bup\s+to\s+\d|\bsave\b|%\s+off\b|\bdiscount|\bcould earn|statement\s+credit|\bpromo", re.IGNORECASE
)
_OFFER = re.compile(
    r"\bearn\s+(?:a\s+)?(?:one-time\s+)?(?:\$[\d,]+\s+cash\s+bonus|[\d,]{5,}\s+bonus\s+miles|bonus\s+of\s+[\d,]{5,}"
    r"\s+miles)[^.]*?\b(?:once|when|after)\s+you\s+spend\s+\$[\d,]+",
    re.IGNORECASE,
)


_INTRO_FEE = re.compile(r"\$(\d[\d,]*) annual fee for the first year, and then \$(\d[\d,]*)", re.IGNORECASE)


def _plain(s: str) -> str:
    """Same normalisation as the R-NAME validation rule, so a chosen name always passes it."""
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"[®™℠]", "", s.lower())).strip()


class Adapter(DeclarativeAdapter):
    bank_id = "capital_one"
    parser_version = "capital_one/1.0.0"

    # ------------------------------------------------------------------ helpers
    def _pairs(self, page: ClassifiedPage) -> list[tuple[str, str]]:
        doc = page.doc
        assert doc is not None
        out = []
        for n in doc.select(".showcase-item"):
            h, b = n.css_first(".showcase-headline"), n.css_first(".showcase-body")
            ht = re.sub(r"\s+", " ", doc.node_text(h)).strip() if h is not None else ""
            bt = re.sub(r"\s+", " ", doc.node_text(b)).strip() if b is not None else ""
            if ht or bt:
                out.append((ht, bt))
        return out

    def product_name(self, page: ClassifiedPage) -> str | None:
        doc = page.doc
        if doc is None:
            return None
        visible = _plain(doc.text)
        for h in doc.h1:
            # The Venture page's h1 is a promotion ("Enjoy a $300 stays credit, plus earn 75K bonus miles").
            if not re.search(r"\$|\b(?:earn|enjoy|bonus)\b", h, re.I) and _plain(h) in visible:
                return h.strip()
        line = X.first_line(doc, r"^[\w’'®\s.-]{3,60} from Capital One$")
        if line:
            return line.strip()
        # The document title ("Spark Cash Plus | 2% Cash Back Business Card | Capital One") when the page states it.
        title = doc.title.split("|")[0].strip()
        return title if title and _plain(title) in visible else None

    # ------------------------------------------------------------------ fees and APR
    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        doc = page.doc
        assert doc is not None
        out: dict[str, Sourced[Any]] = {}
        na = NullReason.not_applicable
        pairs = self._pairs(page)
        fee: tuple[str, str] | None = None  # (value text, evidence)
        apr: tuple[str, str] | None = None
        for head, body in pairs:
            hl = head.lower()
            if fee is None and hl == "annual fee":
                fee = (body, f"{head} {body}")
            elif fee is None and re.fullmatch(r"(?:\$0 annual fee|no annual fee)", hl):
                fee = ("$0", head)
            if apr is None and hl in {"purchase rate", "low intro apr"}:
                apr = (body, f"{head} {body}")
            if hl == "credit level" and body:
                out["credit_profile_guidance"] = ctx.field(body, f"{head} {body}", method="table_cell")
            if hl == "security deposit" and (amt := parse_money(body)) is not None:
                out["secured_min_deposit_cents"] = ctx.field(amt, f"{head} {body}", method="table_cell")
        if fee is None:  # small-business template
            line = (
                X.first_line(doc, _INTRO_FEE.pattern)
                or X.first_line(doc, r"^\$\d[\d,]* annual fee$")
                or X.first_line(doc, r"^(?:\$0 annual fee|no annual fee)$")
                or X.first_line(doc, r"\bhas an? (?:annual fee of \$\d[\d,]*|\$\d[\d,]* annual fee)\b")
            )
            fee = (line, line) if line else None
        if apr is None:
            line = X.first_line(
                doc,
                r"^\d{1,2}\.\d{2}%(?:\s*-\s*\d{1,2}\.\d{2}%)? variable APR(?: based on your creditworthiness)?\.?$",
            )
            apr = (line, line) if line else None
        intro_fee = _INTRO_FEE.search(fee[0]) if fee else None
        if fee and intro_fee:
            out["annual_fee_cents"] = ctx.field(int(intro_fee.group(2).replace(",", "")) * 100, fee[1])
            out["intro_annual_fee_cents"] = ctx.field(int(intro_fee.group(1).replace(",", "")) * 100, fee[1])
            out["intro_annual_fee_months"] = ctx.field(12, fee[1])
        elif fee:
            sched = parse_fee_schedule(fee[0])
            if sched.ongoing_cents is not None:
                out["annual_fee_cents"] = ctx.field(sched.ongoing_cents, fee[1], method="table_cell")
                if sched.intro_cents is not None and sched.intro_cents != sched.ongoing_cents:
                    out["intro_annual_fee_cents"] = ctx.field(sched.intro_cents, fee[1], method="table_cell")
                    months = 12 if sched.intro_text and "first year" in sched.intro_text else None
                    out["intro_annual_fee_months"] = ctx.field(months, fee[1], method="table_cell")
                else:
                    out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
                    out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
            else:
                out["annual_fee_cents"] = X.placeholder_or_missing(ctx, fee[0])
        if apr:
            value = apr[0]
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
                out["purchase_apr_min_pct"] = ctx.field(lo, apr[1], method="table_cell")
                out["purchase_apr_max_pct"] = ctx.field(hi, apr[1], method="table_cell")
                out["purchase_apr_variable"] = ctx.field(
                    bool(re.search(r"\bvariable\b", value, re.I)), apr[1], method="table_cell"
                )
            else:
                out["purchase_apr_min_pct"] = X.placeholder_or_missing(ctx, value)
                out["purchase_apr_max_pct"] = X.placeholder_or_missing(ctx, value)
            intro = _INTRO.search(value)
            if intro:
                out["intro_purchase_apr_pct"] = ctx.field(
                    Decimal(intro.group(1)), apr[1], method="table_cell"
                )
                out["intro_purchase_apr_months"] = ctx.field(int(intro.group(2)), apr[1], method="table_cell")
                if intro.group("bt"):
                    out["intro_bt_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr[1], method="table_cell")
                    out["intro_bt_apr_months"] = ctx.field(int(intro.group(2)), apr[1], method="table_cell")
            else:
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=na)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=na)
        ftf = next(
            (
                f"{h} {b}" if h.lower().startswith("no foreign") else b
                for h, b in pairs
                if re.search(r"\bno foreign transaction fees?\b", f"{h} {b}", re.I)
            ),
            None,
        ) or X.first_line(doc, r"^no foreign transaction fees?\b")
        if ftf:
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), ftf, method="free_text")
        return out

    # ------------------------------------------------------------------ statements
    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        doc = page.doc
        if doc is None:
            return []
        out: list[str] = []
        if key == "reward":
            for head, body in self._pairs(page):
                if _RATE_HEAD.search(head):
                    out.append(
                        body if _RATE_HEAD.search(body) or _EARN_LINE.search(body) else f"{head} {body}"
                    )
                elif head.lower() == "unlimited rewards":
                    out += [p.strip() for p in re.split(r"(?=\bEarn unlimited\b)", body) if p.strip()]
            out += [ln for ln in doc.text.split("\n") if _EARN_LINE.search(ln)]
            uniq: list[str] = []
            for line in out:
                # "3% cash back at grocery stores ..., plus 1% cash back on all other purchases"
                for part in re.split(r",?\s+plus\s+(?=\d)", line):
                    part = part.strip()
                    if part and not _NOT_EARN.search(part) and part not in uniq:
                        uniq.append(part)
            return uniq
        if key == "offer":
            cands = [b for _, b in self._pairs(page)] + doc.text.split("\n")
            for s in cands:
                m = _OFFER.search(s)
                if m and s not in out:
                    out.append(s)
            return out[:1]
        if key in {"offer_footnote", "offer_tier", "credit", "benefit"}:
            return []
        return super().statements(page, key, fallback)

    # ------------------------------------------------------------------ extras
    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        doc = page.doc
        assert doc is not None
        name = c.name or ""
        # Small-business cards live under /small-business/; their names ("Spark Cash") do not say "Business".
        if urlsplit(page.url).path.startswith("/small-business/"):
            line = X.first_line(doc, r"\bbusiness\b")
            c.fields["segment"] = ctx.field("business", line) if line else ctx.field(None, None)
        for net, pat in (("Visa", r"\bVisa\b"), ("Mastercard", r"\bMaster[Cc]ard\b")):
            if re.search(pat, name):
                c.fields["network"] = ctx.field(net, name)
                break
        else:
            c.fields["network"] = ctx.field(None, None)
        # One rate per (category, portal-only); portal rates are kept beside general ones (spot-check round 1).
        c.reward_rates = lowest_rate_per_category(c.reward_rates)
        base = [r for r in c.reward_rates if r.value and r.value.category == "other"]
        c.fields["base_rate"] = (
            ctx.field(base[0].value.rate, base[0].span_text)
            if base and base[0].value
            else ctx.field(None, None)
        )
