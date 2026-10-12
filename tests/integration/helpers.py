from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from bankrec.ingest.adapters import known_parsers
from bankrec.ingest.fetch import FixtureFetcher
from bankrec.ingest.pipeline import Pipeline, RunResult
from bankrec.registry.loader import Registry, load_registry
from bankrec.registry.schema import SourceEntry
from bankrec.settings import Settings

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "example_bank"


def registry() -> Registry:
    return load_registry(include_test_only=True, known_parsers=known_parsers())


def source(reg: Registry, slug: str, fixture: Path | None = None) -> SourceEntry:
    s = next(x for x in reg.sources if x.slug == slug)
    return s.model_copy(update={"fixture_path": str(fixture)}) if fixture else s


def run(
    session: Session,
    settings: Settings,
    reg: Registry,
    sources: list[SourceEntry] | None = None,
    **kw: object,
) -> RunResult:
    p = Pipeline(session, settings, reg, fetcher=FixtureFetcher(settings, REPO), **kw)  # type: ignore[arg-type]
    r = p.run(sources)
    session.commit()
    return r


def mutate(tmp: Path, fixture: str, old: str, new: str, name: str | None = None) -> Path:
    html = (FIX / fixture).read_text()
    assert old in html, old
    out = tmp / (name or fixture)
    out.write_text(html.replace(old, new))
    return out
