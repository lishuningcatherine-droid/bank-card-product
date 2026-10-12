"""One fixture per page type (synthetic Example Bank pages)."""

from pathlib import Path

import pytest

from bankrec.classify.classifier import classify, classify_pdf, classify_retrieval
from bankrec.failures import Failure
from bankrec.ingest.common.html import parse_html
from bankrec.model import PageType

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "example_bank"
DOMAINS = ["examplebank.example"]
BOILER = ["this feature is temporarily unavailable"]
URL = "https://www.examplebank.example/credit-cards/everyday-cash"
NAME = "Example Bank Everyday Cash Card"


def _doc(rel: str):  # type: ignore[no-untyped-def]
    return parse_html((FIX / rel).read_text())


def _cls(rel: str, url: str = URL, entity: str = NAME, kind: str = "product_detail", status: int = 200):  # type: ignore[no-untyped-def]
    d = _doc(rel)
    pre = classify_retrieval(status, url, "text/html", d, DOMAINS, BOILER)
    return pre or classify(url, d, entity, source_kind=kind, boilerplate=BOILER)


def test_product_detail() -> None:
    c = _cls("card_everyday_cash.html")
    assert c.page_type is PageType.official_product_detail and "product_h1" in c.signals


def test_offer_detail() -> None:
    c = _cls("card_voyager_rewards.html", entity="Example Bank Voyager Rewards Card", kind="offer_detail")
    assert c.page_type is PageType.official_offer_detail


def test_hidden_boilerplate_is_still_a_product_page() -> None:
    """BoA-style: hidden 'temporarily unavailable' text on a fully loaded product page."""
    c = _cls("pages/boilerplate_product.html")
    assert c.page_type is PageType.official_product_detail


def test_phrase_alone_never_blocks() -> None:
    """A visible challenge-like phrase on a page with product structure is not 'blocked'."""
    html = (
        (FIX / "card_everyday_cash.html")
        .read_text()
        .replace("<main>", "<main><p>Access Denied to old offers.</p>")
    )
    d = parse_html(html)
    assert classify_retrieval(200, URL, "text/html", d, DOMAINS, []) is None


@pytest.mark.parametrize(
    ("rel", "ptype", "failure", "kwargs"),
    [
        ("pages/blocked.html", PageType.blocked_page, Failure.BOT_CHALLENGE, {}),
        ("pages/empty.html", PageType.empty_page, Failure.EMPTY_PAGE, {}),
        ("pages/login.html", PageType.login_page, Failure.LOGIN_WALL, {}),
        (
            "pages/faq.html",
            PageType.faq,
            Failure.NON_PRODUCT_PAGE,
            {"url": "https://www.examplebank.example/faq"},
        ),
        (
            "pages/article.html",
            PageType.article,
            Failure.NON_PRODUCT_PAGE,
            {"url": "https://www.examplebank.example/learn/choose"},
        ),
        (
            "pages/category.html",
            PageType.category_page,
            Failure.NON_PRODUCT_PAGE,
            {"entity": "multiple", "kind": "listing"},
        ),
        (
            "pages/comparison.html",
            PageType.official_comparison_page,
            None,
            {"entity": "multiple", "kind": "comparison"},
        ),
        ("pages/marketing.html", PageType.official_marketing_page, Failure.NON_PRODUCT_PAGE, {}),
        ("pages/terms.html", PageType.terms_page, None, {"kind": "terms_pdf"}),
        ("pages/unknown.html", PageType.unknown_page, Failure.NON_PRODUCT_PAGE, {}),
    ],
)
def test_page_types(rel: str, ptype: PageType, failure: Failure | None, kwargs: dict[str, str]) -> None:
    c = _cls(rel, **kwargs)
    assert c.page_type is ptype
    assert c.failure is failure
    assert c.signals or ptype is PageType.unknown_page


def test_blocked_by_status() -> None:
    c = classify_retrieval(403, URL, "text/html", None, DOMAINS, [])
    assert c is not None and c.page_type is PageType.blocked_page and c.failure is Failure.HTTP_BLOCKED
    c = classify_retrieval(404, URL, "text/html", None, DOMAINS, [])
    assert c is not None and c.page_type is PageType.invalid_page and c.failure is Failure.HTTP_ERROR


def test_invalid_off_domain_redirect() -> None:
    c = classify_retrieval(
        200, "https://evil.example.net/x", "text/html", _doc("card_everyday_cash.html"), DOMAINS, []
    )
    assert c is not None and c.page_type is PageType.invalid_page and c.failure is Failure.REDIRECT_OFF_DOMAIN


def test_pdf_terms() -> None:
    assert (
        classify_pdf("Pricing and Terms\nAnnual Percentage Rate (APR) for Purchases 19.99%\n" * 5).page_type
        is PageType.pdf_terms
    )
    assert classify_pdf("hello").page_type is PageType.unknown_page
