from datetime import UTC, date, datetime, timedelta

from bankrec.dedup.canonical import canonical_key, norm_name, offer_key
from bankrec.dedup.fuzzy import KeyInfo, find_fuzzy
from bankrec.freshness import is_stale, offer_state, product_label
from bankrec.publish.changes import diff_offers, diff_product

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def test_canonical_key_normalization() -> None:
    a = canonical_key("chase", "credit_card", "consumer", "Chase Freedom Unlimited® Credit Card")
    b = canonical_key("chase", "credit_card", "consumer", "chase freedom unlimited card")
    assert a == b == "chase:credit_card:consumer:chase freedom unlimited:-"
    assert canonical_key("x", "credit_card", "business", "Ink Cash") != canonical_key(
        "x", "credit_card", "consumer", "Ink Cash"
    )
    assert norm_name("Example Air Miles Card from Example Bank", "Example Bank") == "example air miles"


def test_offer_key_ignores_url_but_not_amount() -> None:
    base = {
        "offer_type": "card_welcome",
        "amount_qualifier": "exact",
        "amount_min": 1,
        "amount_max": 1,
        "offer_url": "https://a",
    }
    assert offer_key("k", base) == offer_key("k", {**base, "offer_url": "https://b"})
    assert offer_key("k", base) != offer_key("k", {**base, "amount_max": 2, "amount_min": 2})


def test_fuzzy_routes_to_review_and_distinct_variants() -> None:
    a = KeyInfo(
        "b:credit_card:consumer:sapphire preferred:-",
        "b",
        "credit_card",
        "sapphire preferred",
        "consumer",
        9500,
    )
    b = KeyInfo(
        "b:credit_card:consumer:sapphire preferred visa:-",
        "b",
        "credit_card",
        "sapphire preferred visa",
        "consumer",
        9500,
    )
    c = KeyInfo(
        "b:credit_card:consumer:sapphire reserve:-", "b", "credit_card", "sapphire reserve", "consumer", 55000
    )
    props = find_fuzzy([a, b, c])
    ab = next(p for p in props if {p.a, p.b} == {a.key, b.key})
    assert ab.decision == "manual" and ab.proposed is not None
    for p in props:
        if c.key in (p.a, p.b):
            assert p.proposed is None and "proposed distinct" in p.reason
    assert all(p.decision == "manual" for p in props)


def test_fuzzy_ignores_shared_bank_prefix() -> None:
    a = KeyInfo(
        "example_bank:checking:personal:example bank everyday:-",
        "example_bank",
        "checking",
        "example bank everyday",
        "personal",
    )
    b = KeyInfo(
        "example_bank:checking:personal:example bank online:-",
        "example_bank",
        "checking",
        "example bank online",
        "personal",
    )
    assert find_fuzzy([a, b]) == []


def _snap(**fields):  # type: ignore[no-untyped-def]
    return {"fields": fields, "reward_rates": [], "benefits": []}


def test_change_policy_thresholds() -> None:
    minor = diff_product(_snap(apy_pct="4.00"), _snap(apy_pct="4.25"))
    assert [c.change_class for c in minor] == ["minor"]
    major = diff_product(_snap(apy_pct="4.00"), _snap(apy_pct="4.26"))
    assert [c.change_class for c in major] == ["major"]
    uni = diff_product(
        _snap(purchase_apr_min_pct="19.24", purchase_apr_max_pct="28.24"),
        _snap(purchase_apr_min_pct="19.74", purchase_apr_max_pct="28.74"),
    )
    assert {c.change_class for c in uni} == {"minor"}
    non = diff_product(
        _snap(purchase_apr_min_pct="19.24", purchase_apr_max_pct="28.24"),
        _snap(purchase_apr_min_pct="19.74", purchase_apr_max_pct="28.24"),
    )
    assert {c.change_class for c in non} == {"major"}
    big = diff_product(
        _snap(purchase_apr_min_pct="19.24", purchase_apr_max_pct="28.24"),
        _snap(purchase_apr_min_pct="19.75", purchase_apr_max_pct="28.75"),
    )
    assert {c.change_class for c in big} == {"major"}
    fee = diff_product(_snap(annual_fee_cents=0), _snap(annual_fee_cents=9500))
    assert fee[0].change_class == "major"
    rr = diff_product(
        {"fields": {}, "reward_rates": [{"category": "dining", "rate": "3"}], "benefits": []},
        {"fields": {}, "reward_rates": [{"category": "dining", "rate": "2"}], "benefits": []},
    )
    assert rr[0].change_class == "major" and rr[0].field == "reward_rates"
    tiers_old = [{"min_balance_cents": 0, "max_balance_cents": None, "apy_pct": "1.00"}]
    tiers_new = [{"min_balance_cents": 0, "max_balance_cents": None, "apy_pct": "1.20"}]
    assert diff_product(_snap(apy_tiers=tiers_old), _snap(apy_tiers=tiers_new))[0].change_class == "minor"
    assert diff_product(_snap(overdraft_summary="a"), _snap(overdraft_summary="b"))[0].change_class == "info"


def test_offer_changes() -> None:
    old = {"k1": {"offer_type": "card_welcome"}}
    assert diff_offers(old, {}, product_is_new=False)[0].rule == "offer_disappeared"
    ch = diff_offers(old, {"k2": {"offer_type": "card_welcome"}}, product_is_new=False)
    assert {c.rule for c in ch} == {"offer_disappeared", "offer_changed"} and all(
        c.change_class == "major" for c in ch
    )
    new = diff_offers({}, {"k3": {"offer_type": "checking_bonus"}}, product_is_new=False)
    assert new[0].rule == "offer_appeared" and new[0].change_class == "major"
    assert diff_offers({}, {"k3": {"offer_type": "x"}}, product_is_new=True) == []


def test_request_time_expiry_and_stale() -> None:
    fresh = NOW - timedelta(days=1)
    assert offer_state("current", date(2026, 10, 11), fresh, NOW) == "expired"
    assert offer_state("current", date(2026, 10, 12), fresh, NOW) == "current"  # expires end of day ET
    late = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)  # 23:00 ET on Oct 12 → still current
    assert offer_state("current", date(2026, 10, 12), fresh, late) == "current"
    assert offer_state("current", None, NOW - timedelta(days=15), NOW) == "stale"
    assert offer_state("current", None, fresh, NOW, audience="targeted") == "targeted"
    assert offer_state("recheck_pending", None, fresh, NOW) == "recheck_pending"
    assert is_stale(NOW - timedelta(days=8), "apy", NOW) and not is_stale(NOW - timedelta(days=6), "apy", NOW)
    assert is_stale(None, "terms", NOW)


def test_product_label() -> None:
    kw = dict(
        published=True,
        terms_confirmed_at=NOW,
        apy_confirmed_at=NOW,
        product_type="savings",
        missing_key=[],
        recheck_pending=False,
        provider_only_fields=[],
        now=NOW,
    )
    assert product_label(**kw)[0] == "verified"
    assert product_label(**{**kw, "apy_confirmed_at": NOW - timedelta(days=8)})[0] == "partially_verified"
    assert product_label(**{**kw, "missing_key": ["fee_waivers"]})[1] == ["information missing: fee_waivers"]
    assert product_label(**{**kw, "recheck_pending": True})[0] == "partially_verified"
    assert product_label(**{**kw, "provider_only_fields": ["network"]})[0] == "partially_verified"
    assert product_label(**{**kw, "terms_confirmed_at": NOW - timedelta(days=61)})[0] == "partially_verified"
    assert product_label(**{**kw, "published": False})[0] == "under_review"


def test_merge_treats_differently_worded_names_as_aliases() -> None:
    """A terms page titled "X" and the product page "X Credit Card" share a canonical key: alias, not conflict."""
    from datetime import UTC, datetime

    from bankrec.candidate import ProductCandidate
    from bankrec.model import PageType, ProductType, Sourced
    from bankrec.publish.merge import Meta, merge

    def cand(name: str, fee: int, pt: PageType) -> ProductCandidate:
        c = ProductCandidate(
            bank_id="example_bank",
            product_type=ProductType.credit_card,
            source_id=name,
            url="https://www.examplebank.example/x",
            page_type=pt,
            parser_name="example_bank",
            parser_version="t",
            retrieved_at=datetime.now(UTC),
        )
        c.fields["official_name"] = Sourced(value=name, span_text=name)
        c.fields["annual_fee_cents"] = Sourced(value=fee, span_text="x")
        return c

    now = datetime.now(UTC)
    a = cand("Example Bank Card Credit Card", 0, PageType.official_product_detail)
    b = cand("Example Bank Card", 0, PageType.terms_page)
    mp = merge(
        [(a, Meta("a", None, "u", "p", "v", now, 100)), (b, Meta("b", None, "u", "p", "v", now, 80))], "k"
    )
    assert mp.conflicts == [] and mp.aliases == {"Example Bank Card Credit Card", "Example Bank Card"}
    c = cand("Example Bank Card", 9500, PageType.terms_page)
    mp = merge(
        [(a, Meta("a", None, "u", "p", "v", now, 100)), (c, Meta("c", None, "u", "p", "v", now, 80))], "k"
    )
    assert [x["field"] for x in mp.conflicts] == [
        "annual_fee_cents"
    ]  # a real difference still goes to review


def test_filling_a_missing_field_is_minor_but_removing_one_is_major() -> None:
    """config/change_policy.yaml: previously_missing_filled: minor (DESIGN §24.14)."""
    from bankrec.publish.changes import diff_product

    old = {
        "fields": {"foreign_tx_fee_pct": None, "annual_fee_cents": 9500},
        "reward_rates": [],
        "benefits": [],
    }
    new = {
        "fields": {"foreign_tx_fee_pct": "3", "annual_fee_cents": 9500},
        "reward_rates": [],
        "benefits": [],
    }
    [ch] = diff_product(old, new)
    assert (ch.field, ch.change_class, ch.rule) == (
        "foreign_tx_fee_pct",
        "minor",
        "previously_missing_filled",
    )
    [ch] = diff_product(new, old)
    assert (ch.change_class, ch.rule) == ("major", "value_added_or_removed")
