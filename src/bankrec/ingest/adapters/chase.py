"""Chase adapter (creditcards.chase.com card pages).

Built from verbatim official pages retrieved on 2026-10-13 (``tests/fixtures/chase/RETRIEVED.txt``); behaviour is
pinned by value-asserting tests in ``tests/adapters/test_chase.py``. See ``docs/adapters/chase.md``.

Page structure (all templates seen: personal "Halo", Sapphire, business, Hyatt-style):

* the annual fee and purchase APR sit in labelled blocks: an ``h2``/``h3`` reading "ANNUAL FEE" or "APR" followed
  by a paragraph, or (Sapphire template) ``…__aprfee--fee`` / ``…__aprfee--apr`` paragraphs;
* earn rates are paragraphs in the rewards-and-benefits section, or ``cmp-reward__element`` tiles (rate + text);
* the welcome offer is the "NEW CARDMEMBER OFFER" block. A crossed-out previous amount is hidden by the shared text
  renderer, so only the current amount is read;
* the Pricing & Terms pages on ``sites.chase.com`` are disallowed for all crawlers by robots.txt and are never
  fetched. Fields that appear only there (foreign transaction fee when not "none", balance-transfer and cash-advance
  terms) stay missing.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters.base import ClassifiedPage, DeclarativeAdapter, lowest_rate_per_category
from bankrec.ingest.common import extract as X
from bankrec.ingest.common.html import scoped
from bankrec.model import ExtractionContext, NullReason, PageType, RewardRateRec, Sourced
from bankrec.parsers.money import parse_fee_schedule, parse_money

_LABELS = {"ANNUAL FEE": "fee", "APR": "apr"}
_RANGE = re.compile(r"(\d{1,2}\.\d{2})%\s*(?:–|-|to)\s*(\d{1,2}\.\d{2})%")
_SINGLE = re.compile(r"(\d{1,2}\.\d{2})%\s+variable APR", re.IGNORECASE)
_INTRO = re.compile(
    r"(\d{1,2}(?:\.\d+)?)% intro APR for (\d{1,2}) months from account opening on purchases"
    r"(?P<bt> and balance transfers)?",
    re.IGNORECASE,
)
_FTF_NONE = re.compile(r"^no foreign transaction fees?\b", re.IGNORECASE)
_AU_FEE = re.compile(r"\$(\d[\d,]*) for each authorized user", re.IGNORECASE)
# The generic "Offers may vary depending on where you apply, for example online or in a branch" notice is printed
# on every Chase page; it describes channel differences, not the amount of the offer shown online.
_CHANNEL_NOTICE = re.compile(r"^offers may vary depending on where you apply", re.IGNORECASE)
_OFFER_LEAD = re.compile(
    r"^earn\s+(?:up\s+to\s+)?(?:a\s+)?(?:\$[\d,]+|[\d,]{4,}\s+(?:bonus\s+)?(?:points|miles|avios)\b)",
    re.IGNORECASE,
)
# An earn-rate statement leads with its rate ("3x points on dining", "Earn 3% on dining", "Plus, 1% cash back").
_RATE_LEAD = re.compile(
    r"^(?:new!?\s+)?(?:(?:and|plus|in\s+addition),?\s+)?(?:earn\s+)?(?:a\s+total\s+of\s+)?(?:unlimited\s+)?"
    r"\d{1,2}(?:\.\d{1,2})?\s*(?:%|x\b|\s+(?:points?|miles?|avios)\s+(?:per|for\s+(?:each|every))\b)"
    r"|\bearn\s+(?:unlimited\s+)?\d(?:\.\d{1,2})?%\s+cash\s+back\s+on\s+all\s+purchases",
    re.IGNORECASE,
)
# Discounts, "up to" stacked totals and partner promotions are not earn rates.
# Discounts, "up to" and "total" stacked rates, statement-credit rebates, partner promotions and rates limited to large purchases
# are not general earn rates.
_NOT_EARN = re.compile(
    r"\bup\s+to\s+\d|\bsave\b|%\s+off\b|\bdiscount|\bpromo|inflight|on\s+board|\b\d+%\s+back\s+(?:on|as)\b|"
    r"statement\s+credit|purchases?\s+of\s+\$[\d,]+\s+or\s+more|large\s+purchases|"
    # "14X total points at Marriott hotels" / "9x total miles on eligible United flights" stack loyalty-program earn on
    # top of the card's own rate; a named-merchant promotion ("5% total cash back on Lyft rides", "10x total points on
    # eligible Peloton equipment") is the card's own rate.
    r"\btotal\b(?!\s+(?:of\s+\S+\s+)?(?:cash\s+back|points|miles)\s+on\s+(?:eligible\s+|qualifying\s+)?(?:lyft|peloton)\b)|"
    # APR statements and airline-program earn ("6x miles on the fare ... as a MileagePlus member") are not card earn
    r"\bAPR\b|\bas an? [\w ]{0,40}member\b|\bon top of the\b|"
    # Points Boost: "up to 1.5x or 2x depending on your card and the offer" is a redemption value, not earn
    r"\bdepending on your card\b",
    re.IGNORECASE,
)
_GIFT_PLUS_EARN = re.compile(
    r"^(?:\$[\d,]+\s+Offer\s+)?(?P<gift>Get\s+an?\s+\$[\d,]+\s+[^+]{0,60}?Gift\s+Card[^+]*?)\s*\+\s*(?P<earn>earn\s+.+)$",
    re.IGNORECASE,
)
# "... Through December 31, 2026, these purchases will earn 3X ...": one statement (the second rate refers back)
_BACK_REF = re.compile(r"\bthese\s+purchases\s+will\s+earn\b", re.IGNORECASE)
# A spend limit we could not parse ("on $150K combined spend") makes the rate's cap unknown.
_UNPARSED_CAP = re.compile(r"\bcombined\b|\bmax(?:imum)?\b|\bon\s+the\s+first\s+\$|\$\d+K\b", re.IGNORECASE)
_MULTI_RATE = re.compile(r",\s*(?:and\s+)?(?=\d{1,2}(?:\.\d{1,2})?\s*(?:%|x\b))", re.IGNORECASE)


def _plain(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"[®™℠]", "", s.lower())).strip()


class Adapter(DeclarativeAdapter):
    bank_id = "chase"
    parser_version = "chase/1.0.0"

    # ------------------------------------------------------------------ name
    def product_name(self, page: ClassifiedPage) -> str | None:
        if page.doc is None:
            return None
        if page.page_type in (PageType.terms_page, PageType.pdf_terms):
            # Pricing & Terms pages (manual capture only) are titled by document, not card: use the registry's
            # expected name when the page states it.
            want = page.source.expected_entity
            return want if _plain(want) in _plain(page.text) else None
        # The business Sapphire page's h1 is a stylised "SAPPHIRE RESERVE"; the full name is in the card-name title.
        for sel in ("[class*='cardNameTitle']", "h1"):
            for n in page.doc.select(sel):
                t = re.sub(r"\s+", " ", page.doc.node_text(n)).strip()
                if t and not t.isupper():
                    return t
        return None

    # ------------------------------------------------------------------ fees and APR
    def _blocks(self, page: ClassifiedPage) -> dict[str, str]:
        """{"fee"|"apr": "<label line> <value line>"} from the labelled summary blocks."""
        doc = page.doc
        assert doc is not None
        out: dict[str, str] = {}
        for h in doc.select("h2, h3"):
            key = _LABELS.get(doc.node_text(h).strip().upper())
            if key is None or key in out:
                continue
            sib = h.next
            while sib is not None and sib.tag == "-text":
                sib = sib.next
            if sib is not None and sib.tag == "p":
                out[key] = doc.node_text(h).strip() + "\n" + doc.node_text(sib).replace("\n", " ")
        # Newer card-marketplace template (seen 2026-10-13 on some cards): label and value on one line,
        # "ANNUAL FEE$0†" / "APR18.49%–27.99% variable APR.†".
        lines = doc.text.split("\n")
        for i, ln in enumerate(lines):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            # the same blocks laid out as flex items: "ANNUAL FEE" / "$0†", "APR" / "18.49%–27.99% variable APR.†"
            if "fee" not in out and ln.strip().upper() == "ANNUAL FEE" and re.match(r"^\$\d", nxt):
                out["fee"] = f"{ln}\n{nxt}"
            if (
                "apr" not in out
                and ln.strip() == "APR"
                and re.match(r"^(?:[A-Z][^:\n]{0,40}APR:\s*)?\d{1,2}(?:\.\d+)?%", nxt)
            ):
                out["apr"] = f"{ln}\n{nxt}"
            if "fee" not in out and re.match(r"^ANNUAL FEE\s*\$\d", ln):
                out["fee"] = ln
            # third template (2026-10-14, Sapphire Reserve for Business): "$795 annual fee†; Employee Cards at no ..."
            if "fee" not in out and re.match(r"^\$[\d,]+ annual fee\b", ln, re.IGNORECASE):
                out["fee"] = ln
            # also "APRFlex for Business variable APR: 17.99%–28.74%.†" (2026-10-14)
            if "apr" not in out and re.match(r"^APR(?:\s*|[A-Z][^:\n]{0,40}APR:\s*)\d{1,2}(?:\.\d+)?%", ln):
                out["apr"] = ln
        for key, sel in (("fee", "[class*='aprfee--fee'] p"), ("apr", "[class*='aprfee--apr'] p")):
            if key not in out:
                for n in doc.select(sel):
                    t = doc.node_text(n).replace("\n", " ").strip()
                    if t:
                        out[key] = t
                        break
        return out

    def fees_and_rates(self, page: ClassifiedPage, ctx: ExtractionContext) -> dict[str, Sourced[Any]]:
        if page.page_type in (PageType.terms_page, PageType.pdf_terms):
            return super().fees_and_rates(page, ctx)  # the Schumer box: label/value table rows
        doc = page.doc
        assert doc is not None
        out: dict[str, Sourced[Any]] = {}
        blocks = self._blocks(page)
        na = NullReason.not_applicable
        fee = blocks.get("fee")
        if fee:
            value = re.sub(r"^ANNUAL FEE\s*", "", fee.split("\n", 1)[-1])
            sched = parse_fee_schedule(value)
            if sched.ongoing_cents is not None:
                out["annual_fee_cents"] = ctx.field(sched.ongoing_cents, fee, method="table_cell")
                if sched.intro_cents is not None:
                    out["intro_annual_fee_cents"] = ctx.field(sched.intro_cents, fee, method="table_cell")
                    months = 12 if sched.intro_text and "first year" in sched.intro_text else None
                    out["intro_annual_fee_months"] = ctx.field(months, fee, method="table_cell")
                else:
                    out["intro_annual_fee_cents"] = ctx.field(None, None, null_reason=na)
                    out["intro_annual_fee_months"] = ctx.field(None, None, null_reason=na)
            else:
                out["annual_fee_cents"] = X.placeholder_or_missing(ctx, value)
            au = _AU_FEE.search(fee)
            if au:
                out["au_fee_cents"] = ctx.field(int(au.group(1).replace(",", "")) * 100, fee)
        apr = blocks.get("apr")
        if apr:
            value = re.sub(r"^APR(?=\d)", "", apr.split("\n", 1)[-1])
            rng = _RANGE.search(value)
            single = _SINGLE.search(value)
            lo: Decimal | None
            hi: Decimal | None
            if rng:
                lo, hi = Decimal(rng.group(1)), Decimal(rng.group(2))
            elif single:
                lo = hi = Decimal(single.group(1))
            else:
                lo = hi = None
            if lo is not None:
                variable = bool(re.search(r"\bvariable\b", value, re.IGNORECASE))
                out["purchase_apr_min_pct"] = ctx.field(lo, apr, method="table_cell")
                out["purchase_apr_max_pct"] = ctx.field(hi, apr, method="table_cell")
                out["purchase_apr_variable"] = ctx.field(variable, apr, method="table_cell")
            else:
                out["purchase_apr_min_pct"] = X.placeholder_or_missing(ctx, value)
                out["purchase_apr_max_pct"] = X.placeholder_or_missing(ctx, value)
            intro = _INTRO.search(value)
            if intro:
                out["intro_purchase_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="table_cell")
                out["intro_purchase_apr_months"] = ctx.field(int(intro.group(2)), apr, method="table_cell")
                if intro.group("bt"):
                    out["intro_bt_apr_pct"] = ctx.field(Decimal(intro.group(1)), apr, method="table_cell")
                    out["intro_bt_apr_months"] = ctx.field(int(intro.group(2)), apr, method="table_cell")
            else:
                out["intro_purchase_apr_pct"] = ctx.field(None, None, null_reason=na)
                out["intro_purchase_apr_months"] = ctx.field(None, None, null_reason=na)
        ftf = X.first_line(doc, _FTF_NONE.pattern)
        if ftf:
            out["foreign_tx_fee_pct"] = ctx.field(Decimal("0"), ftf, method="free_text")
        dep = X.first_line(doc, r"minimum security deposit of \$\d")
        if dep and (amt := parse_money(dep)) is not None:
            out["secured_min_deposit_cents"] = ctx.field(amt, dep, method="free_text")
        return out

    def offer_note(self, page: ClassifiedPage) -> str | None:
        base = super().offer_note(page)
        text = page.doc.text if page.doc is not None else page.text
        for ln in text.split("\n"):
            t = re.sub(r"^NEW CARDMEMBER OFFER\s*", "", ln.strip(), flags=re.IGNORECASE)
            if gm := _GIFT_PLUS_EARN.match(t):
                gift = gm.group("gift").rstrip("*† ")
                return f"Plus «{gift}» (a gift card; not counted in recommendations)." + (
                    f" {base}" if base else ""
                )
        return base

    # ------------------------------------------------------------------ statements
    def statements(self, page: ClassifiedPage, key: str, fallback: str | None) -> list[str]:
        doc = page.doc
        if doc is None:
            return []
        out: list[str] = []
        if key == "offer":
            for n in doc.select(self.rules["offer_selector"]):
                if n.attributes.get("data-slot") == "offer":
                    # third template: a flag ("OUR BEST OFFER RETURNS"), then "Earn 200,000 points" / "after you spend
                    # $30,000 ... in your first 6 months ...", then value call-outs
                    lines = [ln for ln in doc.node_text(n).split("\n") if ln.strip()]
                    i = next((k for k, ln in enumerate(lines) if _OFFER_LEAD.search(ln)), None)
                    if i is not None and i + 1 < len(lines) and re.match(r"^after\b", lines[i + 1], re.I):
                        t = f"{lines[i]} {lines[i + 1]}"
                        if t not in out:
                            out.append(t)
                    continue
                t = re.sub(r"\s+", " ", doc.node_text(n)).strip()
                if "newcardmemberoffer" in (n.attributes.get("class") or "") or t.upper().startswith(
                    "NEW CARDMEMBER OFFER"
                ):
                    t = re.sub(r"^NEW CARDMEMBER OFFER\s*", "", t, flags=re.IGNORECASE)
                    # "$500 Offer Get a $300 Disney Gift Card eGift to use today upon approval* + earn a $200
                    # statement credit after you spend $1,000 ...": the spend bonus is the offer; the gift card is
                    # kept as the offer's note (offer_note), never counted
                    if gm := _GIFT_PLUS_EARN.match(t):
                        t = gm.group("earn")
                    # Only plain bonuses ("Earn 75,000 points", "Earn a $200 bonus"). Gift cards, free nights,
                    # memberships and partner credits are not cash/points bonuses and are left out.
                    if t and _OFFER_LEAD.search(t) and t not in out:
                        out.append(t)
            return out
        if key == "offer_footnote":
            return [
                s
                for s in super().statements(page, key, None)
                if not _CHANNEL_NOTICE.search(s) and re.search(r"new cardmember bonus", s, re.IGNORECASE)
            ]
        if key == "reward":
            for n in doc.select(".cmp-reward__element"):
                # Sapphire tiles: "5x points" + "on Chase Travel*"; a trailing "and 1X points on all other
                # purchases" paragraph is a separate statement.
                pts = n.css_first(".cmp-reward__points")
                head = doc.node_text(pts).strip() if pts is not None else ""
                paras = [doc.node_text(p).replace("\n", " ").strip() for p in n.css(".cmp-reward__text p")]
                if head and paras:
                    out.append(f"{head} {paras[0]}")
                    out += paras[1:]
            # A line starting in lower case continues the previous one ("3X on Travel and Business" /
            # "categories on $150K combined spend.").
            # Earn statements come from the marketing content, never the "Offer Details" legal overlay
            # (cmp-popup--cardofferdetails), whose long paragraphs mention categories in exclusions.
            body = scoped(
                doc, "body", "[class*='cmp-popup--cardofferdetails'], [class*='experiencefragment-modal']"
            )
            for line in body.text.split("\n"):
                if X.is_program_paragraph(line):
                    continue  # the rewards-program terms are read clause by clause (DESIGN §24.17 B)
                if out and line[:1].islower() and not out[-1].endswith((".", "*", "†")):
                    out[-1] = f"{out[-1]} {line}"
                else:
                    out.append(line)
            stmts: list[str] = []
            for line in out:
                if re.search(r"\bAPR\b", line):
                    continue  # APR statements are never earn statements (split pieces would lose the word "APR")
                # one sentence, then one rate clause at a time ("Earn 3 Avios ... In addition earn 2 Avios ...")
                sentences = re.split(r"(?<=[a-z*®])\.[*†‡¤]*\s+(?=[A-Z])", line.strip())
                # "... at grocery stores. Through December 31, 2026, these purchases will earn 3X points per $1
                # spent.": the second sentence refers back to the first one's categories, so they stay together.
                # "Save 10% on select purchases at DisneyStore.com": a discount; once split into rate clauses the
                # word "Save" would be lost
                sentences = [x for x in sentences if not re.search(r"\bsave\s+\d+%|\b\d+%\s+off\b", x, re.I)]
                for k in range(len(sentences) - 1, 0, -1):
                    if re.match(
                        r"^through\b[^.]{0,40},\s+these\s+purchases\s+will\s+earn\b", sentences[k], re.I
                    ):
                        sentences[k - 1 : k + 1] = [f"{sentences[k - 1]}. {sentences[k]}"]
                parts = [
                    p
                    for sent in sentences
                    for c in ([sent] if _BACK_REF.search(sent) else X.split_rate_clauses(sent))
                    for p in ([c] if _BACK_REF.search(c) else _MULTI_RATE.split(c))
                ]
                for part in parts:
                    part = part.strip()
                    if _RATE_LEAD.search(part) and not _NOT_EARN.search(part) and part not in stmts:
                        stmts.append(part)
            return stmts
        return super().statements(page, key, fallback)

    # ------------------------------------------------------------------ extras
    def card_extras(self, page: ClassifiedPage, ctx: ExtractionContext, c: ProductCandidate) -> None:
        # Network: from the product name when it says so; otherwise unique within the scoped product content.
        name = c.name or ""
        for net, pat in (("Visa", r"\bVisa\b"), ("Mastercard", r"\bMaster[Cc]ard\b")):
            if re.search(pat, name):
                c.fields["network"] = ctx.field(net, name)
                break
        else:
            c.fields["network"] = ctx.field(None, None)
        self.partner_rates(c)
        # The same rate is often stated twice (summary and detail); the capped statement is the precise one.
        best: dict[tuple[Any, ...], Sourced[RewardRateRec]] = {}
        for r in c.reward_rates:
            v = r.value
            if v is None or (v.cap_cents is None and (_UNPARSED_CAP.search(v.text) or v.is_rotating)):
                continue
            k = (v.category, v.rate, v.rate_unit, v.ends_on)  # a dated promotion is its own rate
            cur = best[k].value if k in best else None
            if cur is None or (cur.cap_cents is None and v.cap_cents is not None):
                best[k] = r
        c.reward_rates = lowest_rate_per_category(list(best.values()))
        base = [r for r in c.reward_rates if r.value and r.value.category == "other"]
        if len({r.value.rate for r in base if r.value}) > 1:
            c.fields["base_rate"] = ctx.field(None, None, null_reason=NullReason.conflict)
            c.reward_rates = [r for r in c.reward_rates if r.value and r.value.category != "other"]
        # Credits repeated in several sections are one credit.
        seen: set[tuple[Any, ...]] = set()
        uniq = []
        for b in c.benefits:
            bv = b.value
            bk = (bv.benefit_type, bv.amount_cents, bv.period) if bv else None
            if bk is None or bk in seen:
                continue
            seen.add(bk)
            uniq.append(b)
        c.benefits = uniq
