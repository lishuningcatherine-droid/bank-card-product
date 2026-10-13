from datetime import UTC, datetime
from pathlib import Path

from bankrec.candidate import ProductCandidate
from bankrec.ingest.adapters import get_adapter
from bankrec.ingest.adapters.base import ClassifiedPage
from bankrec.ingest.common.html import parse_html
from bankrec.model import PageType
from bankrec.registry.loader import load_registry

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def run_adapter(adapter: str, fixture: Path, slug: str, *, url: str | None = None) -> ProductCandidate:
    """Run ``adapter`` over a page. For real-bank adapters the page is a synthetic Example Bank page: it exercises
    the adapter's logic without attributing any content to the real bank."""
    reg = load_registry(include_test_only=True)
    src = next(s for s in reg.sources if s.slug == slug and s.bank_id == "example_bank")
    doc = parse_html(fixture.read_text())
    page = ClassifiedPage(
        source=src,
        bank=reg.bank("example_bank"),
        url=url or str(src.source_url),
        page_type=PageType.official_product_detail,
        retrieved_at=datetime.now(UTC),
        text=doc.text,
        doc=doc,
    )
    return get_adapter(adapter).extract(page)[0]


def verbatim_fixtures(bank_id: str) -> list[Path]:
    d = FIX / bank_id
    return sorted(p for p in d.glob("*.html")) if (d / "RETRIEVED.txt").exists() else []


def run_official(bank_id: str, slug: str, fixture: str) -> ProductCandidate:
    """Run a real bank's adapter over its verbatim official fixture, as the registry source ``slug``."""
    reg = load_registry(require_sources=False)
    src = next(s for s in reg.sources if s.bank_id == bank_id and s.slug == slug)
    path = FIX / bank_id / fixture
    doc = parse_html(path.read_text(encoding="utf-8"))
    page = ClassifiedPage(
        source=src,
        bank=reg.bank(bank_id),
        url=str(src.source_url),
        page_type=PageType.official_product_detail,
        retrieved_at=datetime.now(UTC),
        text=doc.text,
        doc=doc,
    )
    return get_adapter(reg.bank(bank_id).adapter).extract(page)[0]


def rates(c: ProductCandidate) -> dict[str, tuple[str, int | None]]:
    """{category: ("<rate><unit>", cap_cents)} for compact assertions."""
    out = {}
    for r in c.reward_rates:
        v = r.value
        assert v is not None
        out[v.category] = (f"{v.rate.normalize()}{v.rate_unit}", v.cap_cents)
    return out
