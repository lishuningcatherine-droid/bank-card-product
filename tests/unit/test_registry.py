import shutil
from pathlib import Path

import pytest

from bankrec.ingest.adapters import known_parsers
from bankrec.registry.loader import EmptyRegistryError, RegistryError, load_registry
from bankrec.registry.urls import canonicalize, disallowed_params, domain_allowed, looks_like_referral

CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    shutil.copytree(CONFIG, tmp_path / "config")
    return tmp_path / "config"


def test_real_registry_without_sources_is_an_error() -> None:
    with pytest.raises(EmptyRegistryError):
        load_registry(known_parsers=known_parsers())


def test_test_registry_loads() -> None:
    r = load_registry(include_test_only=True, known_parsers=known_parsers())
    assert len(r.enabled()) == 11
    assert {s.tier for s in r.enabled()} == {"offer", "terms", "apy"}
    assert all(s.requires_render for s in r.enabled() if s.has_offers)


def _write(cfg: Path, text: str) -> None:
    (cfg / "sources" / "example_bank.yaml").write_text(text)


BASE = """bank_id: example_bank
sources:
  - bank_id: example_bank
    slug: {slug}
    product_type: credit_card
    source_url: "{url}"
    source_kind: product_detail
    parser_name: {parser}
    expected_entity: X
    state: {state}
    enabled: {enabled}
"""


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"url": "https://www.evil.example/x"}, "official domain"),
        ({"url": "https://www.examplebank.example/x?utm_source=a"}, "tracking"),
        ({"url": "https://www.examplebank.example/refer/abc"}, "referral"),
        ({"parser": "nope"}, "unknown parser"),
        ({"state": "discovered"}, "never auto-enabled"),
    ],
)
def test_registry_errors(cfg: Path, kw: dict[str, str], msg: str) -> None:
    args = {
        "slug": "a",
        "url": "https://www.examplebank.example/x",
        "parser": "example_bank",
        "state": "curated",
        "enabled": "true",
        **kw,
    }
    _write(cfg, BASE.format(**args))
    with pytest.raises(RegistryError, match=msg):
        load_registry(cfg, include_test_only=True, known_parsers=known_parsers())


def test_duplicate_url_and_malformed(cfg: Path) -> None:
    one = BASE.format(
        slug="a",
        url="https://www.examplebank.example/x",
        parser="example_bank",
        state="curated",
        enabled="true",
    )
    _write(cfg, one + one.split("sources:\n")[1].replace("slug: a", "slug: b"))
    with pytest.raises(RegistryError, match="duplicate URL"):
        load_registry(cfg, include_test_only=True, known_parsers=known_parsers())
    _write(cfg, "bank_id: [unclosed")
    with pytest.raises(RegistryError, match="malformed"):
        load_registry(cfg, include_test_only=True)
    _write(cfg, "")
    with pytest.raises(RegistryError, match="empty"):
        load_registry(cfg, include_test_only=True)


def test_url_helpers() -> None:
    assert (
        canonicalize("HTTPS://WWW.Example.com/a?utm_source=x&id=2#frag", ["id"])
        == "https://www.example.com/a?id=2"
    )
    assert domain_allowed("https://creditcards.chase.com/x", ["chase.com"])
    assert not domain_allowed("https://chase.com.evil.io/x", ["chase.com"])
    assert disallowed_params("https://a.com/x?gclid=1&ok=2", ["ok"]) == ["gclid"]
    assert looks_like_referral("https://a.com/refer-a-friend/x", [])
    assert not looks_like_referral("https://a.com/credit-cards/preferred", [])
