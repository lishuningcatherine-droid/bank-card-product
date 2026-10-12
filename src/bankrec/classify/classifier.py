"""Explainable page classifier (brief §7.1). Ordered rules; every fired signal is recorded.

Never classifies a page as blocked on a phrase alone: a challenge marker counts only together with a blocking
HTTP status or the absence of product structure (no product h1, no rates section, short body).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bankrec.failures import Failure
from bankrec.ingest.common.html import PageDoc
from bankrec.model import PageType
from bankrec.registry.urls import domain_allowed

CHALLENGE_MARKERS = [
    r"access denied",
    r"reference #\s*[\d.a-f]+",
    r"request unsuccessful",
    r"pardon our interruption",
    r"please enable javascript",
    r"_incapsula_",
    r"cf-chl",
    r"px-captcha",
    r"are you a robot",
    r"verify you are human",
    r"captcha",
    r"bot detection",
    r"unusual traffic",
]
LOGIN_MARKERS = [r"\bsign in\b", r"\blog ?in\b", r"\busername\b", r"\bpassword\b"]
ARTICLE_URL = re.compile(
    r"/(?:learn|insights|education|articles?|blog|news|resources/(?:articles|guides))/", re.I
)
FAQ_URL = re.compile(r"/(?:faqs?|help|support|questions)(?:/|$|\.)", re.I)
LOGIN_URL = re.compile(r"/(?:log-?in|sign-?in|logon|auth|secure/)", re.I)
RATE_LABELS = [
    r"annual (?:membership )?fee",
    r"\bapr\b",
    r"annual percentage (?:rate|yield)",
    r"\bapy\b",
    r"monthly (?:maintenance |service )?fee",
    r"foreign transaction",
    r"minimum (?:opening )?deposit",
    r"balance transfer",
]
OFFER_MARKERS = [
    r"\bbonus\b",
    r"welcome offer",
    r"after you spend",
    r"qualifying direct deposit",
    r"\bearn \$\d",
    r"earn \d[\d,]+ (?:bonus )?(?:points|miles)",
]
MIN_BODY_CHARS = 400


@dataclass
class Classification:
    page_type: PageType
    signals: list[str] = field(default_factory=list)
    failure: Failure | None = None
    detail: str = ""


def _norm_name(s: str) -> str:
    s = re.sub(r"[®™℠*]", "", s.lower())
    s = re.sub(r"\b(credit card|card|account)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def name_present(name: str, text: str) -> bool:
    n = _norm_name(name)
    return bool(n) and n in _norm_name(text)


def classify_retrieval(
    status: int | None,
    final_url: str,
    content_type: str,
    doc: PageDoc | None,
    official_domains: list[str],
    boilerplate: list[str],
) -> Classification | None:
    """Retrieval-outcome rules (stage 4). Returns a terminal classification, or None to continue."""
    sig: list[str] = []
    if not domain_allowed(final_url, official_domains):
        return Classification(
            PageType.invalid_page,
            ["redirect_off_domain"],
            Failure.REDIRECT_OFF_DOMAIN,
            f"final URL {final_url}",
        )
    if status is not None and status >= 400:
        sig.append(f"http_{status}")
    if doc is None:
        if status is not None and status >= 400:
            return Classification(
                PageType.blocked_page if status in (401, 403, 429) else PageType.invalid_page,
                sig,
                Failure.HTTP_BLOCKED if status in (401, 403, 429) else Failure.HTTP_ERROR,
            )
        return None
    visible = doc.text
    for b in boilerplate:  # known hidden boilerplate is never a block signal
        visible = re.sub(re.escape(b), " ", visible, flags=re.IGNORECASE)
    markers = [
        m
        for m in CHALLENGE_MARKERS
        if re.search(m, visible, re.IGNORECASE)
        or (re.search(m, doc.html[:20000], re.I) and m in (r"_incapsula_", r"cf-chl", r"px-captcha"))
    ]
    rates = sum(1 for p in RATE_LABELS if re.search(p, visible, re.IGNORECASE))
    has_h1 = bool(doc.h1)
    long_body = len(visible) >= MIN_BODY_CHARS
    if markers:
        sig += [f"challenge:{m}" for m in markers]
    structural_absent = not has_h1 and rates == 0 and not long_body
    if markers and (status in (403, 429, 503) or structural_absent):
        return Classification(
            PageType.blocked_page,
            [*sig, "no_product_structure"] if structural_absent else sig,
            Failure.BOT_CHALLENGE,
            "challenge marker with blocking status or no product structure",
        )
    if status is not None and status in (401, 403, 429):
        return Classification(PageType.blocked_page, sig, Failure.HTTP_BLOCKED)
    if status is not None and status >= 400:
        return Classification(PageType.invalid_page, sig, Failure.HTTP_ERROR)
    if doc.tree.css_first("input[type=password]") is not None and rates == 0:
        return Classification(PageType.login_page, [*sig, "password_input"], Failure.LOGIN_WALL)
    if len(visible.strip()) < 80 and not has_h1:
        return Classification(PageType.empty_page, [*sig, "body_lt_80_chars"], Failure.EMPTY_PAGE)
    return None


def classify(
    url: str, doc: PageDoc, expected_entity: str, *, source_kind: str, boilerplate: list[str] | None = None
) -> Classification:
    """Content rules (stage 5) for a successfully retrieved HTML page."""
    sig: list[str] = []
    text = doc.text
    for b in boilerplate or []:
        text = re.sub(re.escape(b), " ", text, flags=re.IGNORECASE)
    if LOGIN_URL.search(url) or (doc.tree.css_first("input[type=password]") is not None):
        return Classification(PageType.login_page, ["login_url_or_password_input"], Failure.LOGIN_WALL)
    if (
        ARTICLE_URL.search(url)
        or doc.tree.css_first("article [rel=author], .byline, [itemprop=author]") is not None
        or re.search(r"\b\d+\s+min(?:ute)? read\b", text, re.IGNORECASE)
    ):
        return Classification(PageType.article, ["article_url_or_byline"], Failure.NON_PRODUCT_PAGE)
    qa = len(re.findall(r"^(?:q:|.{10,160}\?)$", text, re.MULTILINE))
    if FAQ_URL.search(url) or (
        re.search(r"frequently asked questions", text, re.IGNORECASE) and qa >= 5 and not doc.h1
    ):
        return Classification(PageType.faq, [f"faq_url_or_qa_pairs:{qa}"], Failure.NON_PRODUCT_PAGE)

    rates = [p for p in RATE_LABELS if re.search(p, text, re.IGNORECASE)]
    sig += [f"rate_label:{p}" for p in rates]
    offers = [p for p in OFFER_MARKERS if re.search(p, text, re.IGNORECASE)]
    sig += [f"offer_marker:{p}" for p in offers]
    fee_blocks = len(
        re.findall(
            r"^(?:annual fee|monthly (?:maintenance |service )?fee)\b", text, re.IGNORECASE | re.MULTILINE
        )
    )
    tiles = len(doc.select("[data-product], .product-tile, .card-tile, .product-card"))
    if fee_blocks:
        sig.append(f"fee_blocks:{fee_blocks}")
    if tiles:
        sig.append(f"product_tiles:{tiles}")

    if (
        source_kind == "terms_pdf"
        or re.search(
            r"pricing (?:and|&) terms|rates (?:and|&) fees|cardmember agreement",
            doc.title + " " + " ".join(doc.h1),
            re.IGNORECASE,
        )
    ) and rates:
        return Classification(PageType.terms_page, [*sig, "terms_title"])

    if expected_entity == "multiple":
        if fee_blocks >= 2 or (tiles >= 2 and rates):
            return Classification(PageType.official_comparison_page, sig)
        if tiles >= 2 or source_kind == "listing":
            return Classification(PageType.category_page, sig, Failure.NON_PRODUCT_PAGE)
        return Classification(PageType.unknown_page, sig, Failure.NON_PRODUCT_PAGE)

    h1_match = any(name_present(expected_entity, h) for h in doc.h1)
    if h1_match:
        sig.append("product_h1")
    in_text = name_present(expected_entity, text)
    if in_text:
        sig.append("name_in_text")
    if not in_text:
        return Classification(
            PageType.unknown_page,
            [*sig, "expected_name_absent"],
            Failure.NON_PRODUCT_PAGE,
            f"expected entity {expected_entity!r} not found",
        )
    if tiles >= 3 and not h1_match:
        return Classification(PageType.category_page, sig, Failure.NON_PRODUCT_PAGE)
    if fee_blocks >= 2 and not h1_match:
        return Classification(PageType.official_comparison_page, sig)
    if h1_match and rates:
        if source_kind == "offer_detail" and offers:
            return Classification(PageType.official_offer_detail, sig)
        return Classification(PageType.official_product_detail, sig)
    if offers and (h1_match or source_kind == "offer_detail"):
        return Classification(PageType.official_offer_detail, sig)
    if h1_match:
        return Classification(
            PageType.official_marketing_page, [*sig, "no_rates_section"], Failure.NON_PRODUCT_PAGE
        )
    return Classification(PageType.unknown_page, sig, Failure.NON_PRODUCT_PAGE)


def classify_pdf(text: str) -> Classification:
    if (
        re.search(r"pricing|terms|annual percentage rate|\bapr\b|schumer|fees", text, re.IGNORECASE)
        and len(text) > 200
    ):
        return Classification(PageType.pdf_terms, ["pdf_terms_markers"])
    return Classification(PageType.unknown_page, ["pdf_without_terms_markers"], Failure.NON_PRODUCT_PAGE)
