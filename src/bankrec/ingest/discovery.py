"""Reachability survey and sitemap discovery (brief §6.2). Discovered URLs are never auto-enabled."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml
from selectolax.lexbor import LexborHTMLParser

from bankrec.failures import Failure
from bankrec.ingest.fetch import Fetcher, _classify_exception
from bankrec.registry.loader import Registry
from bankrec.registry.schema import BankConfig
from bankrec.registry.urls import canonicalize, domain_allowed


@dataclass
class ProbeResult:
    bank_id: str
    kind: str  # robots | sitemap
    url: str
    at: str
    status: int | None = None
    failure: str | None = None
    detail: str = ""
    urls_found: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _get(f: Fetcher, url: str) -> tuple[int | None, bytes, Failure | None, str]:
    f.limiter.wait(urlsplit(url).netloc)
    try:
        r = f.client.get(url)
        return r.status_code, r.content, None, ""
    except Exception as e:
        return None, b"", _classify_exception(e), str(e)[:200]


def sitemap_urls(xml: bytes, limit: int = 5000) -> tuple[list[str], list[str]]:
    """(page URLs, nested sitemap URLs) from a sitemap or sitemap index."""
    doc = LexborHTMLParser(xml.decode("utf-8", errors="replace"))
    locs = [n.text(strip=True) for n in doc.css("loc")][:limit]
    nested = [u for u in locs if re.search(r"sitemap[^/]*\.xml", u, re.IGNORECASE)]
    pages = [u for u in locs if u not in nested]
    return pages, nested


def survey_bank(f: Fetcher, bank: BankConfig) -> list[ProbeResult]:
    out: list[ProbeResult] = []
    now = datetime.now(UTC).isoformat()
    robots_url = str(bank.discovery.robots_url) if bank.discovery.robots_url else None
    sitemaps = [str(s) for s in bank.discovery.sitemaps]
    if robots_url:
        status, body, fail, detail = _get(f, robots_url)
        pr = ProbeResult(
            bank.bank_id, "robots", robots_url, now, status, fail.value if fail else None, detail
        )
        if body:
            listed = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", body.decode("utf-8", errors="replace"))
            pr.extra["sitemaps_listed"] = listed
            pr.extra["disallow_count"] = len(
                re.findall(r"(?im)^\s*disallow:", body.decode("utf-8", "replace"))
            )
            sitemaps += [u for u in listed if u not in sitemaps and domain_allowed(u, bank.official_domains)]
        out.append(pr)
    for sm in sitemaps:
        blocked = f.robots.check(sm)
        if blocked is not None:
            out.append(
                ProbeResult(bank.bank_id, "sitemap", sm, now, None, blocked.value, "robots or network")
            )
            continue
        status, body, fail, detail = _get(f, sm)
        pr = ProbeResult(bank.bank_id, "sitemap", sm, now, status, fail.value if fail else None, detail)
        if body and status == 200:
            pages, nested = sitemap_urls(body)
            pr.urls_found, pr.extra["nested"] = len(pages), nested[:50]
        out.append(pr)
    return out


def discover(f: Fetcher, registry: Registry, bank_id: str, config_dir: Path, max_nested: int = 20) -> Path:
    """Write config/sources/<bank>.discovered.yaml from official sitemaps (state: discovered, enabled: false)."""
    bank = registry.bank(bank_id)
    patterns = bank.discovery.sitemap_url_patterns
    curated = {canonicalize(str(s.source_url)) for s in registry.sources if s.bank_id == bank_id}
    queue = [str(s) for s in bank.discovery.sitemaps]
    seen: set[str] = set()
    found: dict[str, str] = {}
    while queue and len(seen) < max_nested:
        sm = queue.pop(0)
        if sm in seen or f.robots.check(sm) is not None:
            continue
        seen.add(sm)
        status, body, fail, _ = _get(f, sm)
        if fail or status != 200:
            continue
        pages, nested = sitemap_urls(body)
        queue += [n for n in nested if domain_allowed(n, bank.official_domains)]
        for u in pages:
            cu = canonicalize(u, bank.meaningful_query_params)
            if cu in curated or not domain_allowed(cu, bank.official_domains):
                continue
            for ptype, regexes in patterns.items():
                if any(re.search(rx, cu) for rx in regexes):
                    found[cu] = ptype
    entries = [
        {
            "bank_id": bank_id,
            "slug": re.sub(r"[^a-z0-9]+", "-", urlsplit(u).path.lower()).strip("-")[:80],
            "product_type": t,
            "source_url": u,
            "source_kind": "product_detail",
            "parser_name": bank.adapter,
            "enabled": False,
            "state": "discovered",
            "expected_entity": "TO CONFIRM",
            "notes": f"discovered from sitemap on {datetime.now(UTC).date()}",
        }
        for u, t in sorted(found.items())
    ]
    path = config_dir / "sources" / f"{bank_id}.discovered.yaml"
    path.write_text(
        "# Discovered URLs: review, set expected_entity, then move to the curated file to enable.\n"
        + yaml.safe_dump({"bank_id": bank_id, "sources": entries}, sort_keys=False),
        encoding="utf-8",
    )
    return path


__all__ = ["ProbeResult", "discover", "httpx", "sitemap_urls", "survey_bank"]
