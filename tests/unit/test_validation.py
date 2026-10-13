from datetime import UTC, datetime

from bankrec.candidate import ProductCandidate
from bankrec.model import OfferRec, PageType, ProductType, Sourced
from bankrec.validation.rules import validate, validate_offer

TEXT = "Example Bank Everyday Cash Card\nAnnual Fee $0\nForeign Transaction Fee 3%\n1% cash back on all purchases"
DOM = ["examplebank.example"]


def _s(v, span):  # type: ignore[no-untyped-def]
    return Sourced(value=v, span_text=span, confidence=0.9)


def cand(
    name: str = "Example Bank Everyday Cash Card",
    page: PageType = PageType.official_product_detail,
    url: str = "https://www.examplebank.example/x",
    **fields,
) -> ProductCandidate:  # type: ignore[no-untyped-def]
    c = ProductCandidate(
        bank_id="example_bank",
        product_type=ProductType.credit_card,
        source_id="e:x",
        url=url,
        page_type=page,
        parser_name="example_bank",
        parser_version="1",
        retrieved_at=datetime.now(UTC),
    )
    c.fields["official_name"] = _s(name, name)
    c.fields["segment"] = _s("consumer", name)
    c.fields["annual_fee_cents"] = _s(0, "Annual Fee $0")
    for k, v in fields.items():
        c.fields[k] = v
    c.set_missing_defaults()
    return c


def test_valid_card() -> None:
    v = validate(cand(), TEXT, DOM)
    # foreign_tx_fee_pct is "conditional" (config/validation.yaml): missing, but it does not block "Verified".
    assert v.status == "valid" and sorted(v.missing_key) == ["base_rate", "reward_currency"]


def test_name_rules() -> None:
    for bad in ["unknown", "Credit Card", "Apply Now"]:
        assert validate(cand(name=bad), TEXT + "\n" + bad, DOM).status == "reject"
    assert validate(cand(name="Example Bank Gold Card"), TEXT, DOM).status == "reject"  # not in page text


def test_domain_and_page_type() -> None:
    assert validate(cand(url="https://evil.example.net/x"), TEXT, DOM).status == "reject"
    assert validate(cand(page=PageType.faq), TEXT, DOM).status == "reject"
    assert validate(cand(page=PageType.official_comparison_page), TEXT, DOM).status == "needs_review"


def test_missing_required_and_confidence() -> None:
    c = cand()
    del c.fields["annual_fee_cents"]
    c.set_missing_defaults()
    assert validate(c, TEXT, DOM).status == "needs_review"
    low = cand()
    low.fields["segment"] = Sourced(value="consumer", span_text="x", confidence=0.5)
    assert validate(low, TEXT, DOM).status == "needs_review"


def test_consistency_and_freshness() -> None:
    c = cand(intro_purchase_apr_pct=_s(25, "x"), purchase_apr_min_pct=_s(20, "x"))
    assert any(r.rule_id == "C-INTRO-APR" for r in validate(c, TEXT, DOM).failed)
    assert validate(cand(annual_fee_cents=_s(500000, "x")), TEXT, DOM).status == "needs_review"
    assert validate(cand(), TEXT, DOM, fresh=False).status == "needs_review"
    assert validate(cand(), TEXT, DOM, conflicts=[{"field": "annual_fee_cents"}]).status == "needs_review"


def _offer(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        offer_type="card_welcome",
        reward_unit="points",
        amount_qualifier="exact",
        amount_min=1,
        amount_max=1,
        requirement_type="spend",
        offer_url="https://x",
        verbatim_text="Earn 1 point after you spend $1",
    )
    return OfferRec(**{**base, **kw})


def test_offer_rules() -> None:
    def st(o, cap=True):  # type: ignore[no-untyped-def]
        return {r.rule_id: r.ok for r in validate_offer(o, cap)}

    assert all(st(_offer()).values())
    assert not st(_offer(verbatim_text="Earn up to 1 point"))["V-QUALIFIER"]
    assert st(_offer(amount_qualifier="up_to", amount_min=None, verbatim_text="Earn up to 1 point"))[
        "V-QUALIFIER"
    ]
    assert not st(_offer(), cap=False)["R-CAPTURE"]
    assert not st(_offer(audience="targeted"))["R-AUDIENCE"]


def test_offer_shape_is_enforced() -> None:
    import pytest

    with pytest.raises(ValueError):
        _offer(amount_qualifier="up_to", amount_min=5)
    with pytest.raises(ValueError):
        _offer(amount_qualifier="exact", amount_min=1, amount_max=2)
    with pytest.raises(ValueError):
        _offer(amount_qualifier="starting_at", amount_min=1, amount_max=1)
