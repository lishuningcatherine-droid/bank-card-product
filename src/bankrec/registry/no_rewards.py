"""Evidence-backed "no rewards program" entries (config/no_rewards.yaml, DESIGN §24.15).

``confirmed()`` is what extraction uses: only owner-confirmed entries. ``verify()`` checks every entry's evidence
against its verbatim fixtures; it is run by the test suite and by ``bankrec evidence check``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bankrec.ingest.common.html import parse_html, scoped
from bankrec.settings import CONFIG_DIR, REPO_ROOT

EVIDENCE_DIR = REPO_ROOT / "tests" / "fixtures" / "evidence"
# Wording that means a terms page describes a rewards program.
_REWARDS_WORDING = re.compile(
    r"rewards? program|cash rewards|bonus cash|earn (?:cash back|points|miles)|\bpoints? per\b|reward dollars",
    re.I,
)


@lru_cache(maxsize=2)
def entries(path: Path | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load((path or CONFIG_DIR / "no_rewards.yaml").read_text(encoding="utf-8")) or {}
    return list(data.get("cards") or [])


def confirmed(path: Path | None = None) -> set[tuple[str, str]]:
    """(bank_id, slug) of entries the owner confirmed (confirmed: true with confirmed_by and confirmed_on)."""
    return {
        (e["bank_id"], e["slug"])
        for e in entries(path)
        if e.get("confirmed") is True and e.get("confirmed_by") and e.get("confirmed_on")
    }


def _text(file: str, base: Path) -> str:
    doc = parse_html((base / file).read_text(encoding="utf-8", errors="replace"))
    if doc.select("main"):  # category pages: product content only, never menus that link every card
        doc = scoped(
            doc, "main", "nav, header, footer, [class*='hamburgermenu'], [class*='footer'], [class*='nav']"
        )
    return re.sub(r"\s+", " ", doc.text)


@dataclass
class Check:
    bank_id: str
    slug: str
    criterion: str  # a | b | c
    file: str
    ok: bool
    detail: str


def verify(path: Path | None = None, base: Path = EVIDENCE_DIR) -> list[Check]:
    out: list[Check] = []
    for e in entries(path):
        b, s, pat = e["bank_id"], e["slug"], re.compile(e["name_pattern"])
        for ev in e.get("listed_on") or []:
            t = _text(ev["file"], base)
            q = re.sub(r"\s+", " ", ev["quote"])
            ok = q in t and bool(pat.search(q))
            out.append(Check(b, s, "a", ev["file"], ok, f"quote {'found' if q in t else 'NOT found'}: {q!r}"))
        for ev in e.get("absent_from") or []:
            t = _text(ev["file"], base)
            hit = pat.search(t)
            lists = ev["lists"] in t
            out.append(
                Check(
                    b,
                    s,
                    "b",
                    ev["file"],
                    hit is None and lists,
                    (
                        "name absent"
                        if hit is None
                        else f"name FOUND: {t[max(0, hit.start() - 40) : hit.end() + 40]!r}"
                    )
                    + f"; page lists {ev['lists']!r}: {lists}",
                )
            )
        tm = e.get("terms")
        if tm:
            t = _text(tm["file"], base)
            w = _REWARDS_WORDING.search(t)
            q = re.sub(r"\s+", " ", tm["quote"])
            out.append(
                Check(
                    b,
                    s,
                    "c",
                    tm["file"],
                    q in t and w is None,
                    f"heading {'found' if q in t else 'NOT found'}; rewards wording: "
                    + ("none" if w is None else repr(t[max(0, w.start() - 40) : w.end() + 40])),
                )
            )
    return out
