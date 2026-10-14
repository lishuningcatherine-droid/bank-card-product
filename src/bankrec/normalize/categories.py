"""Reward-category normalization against the controlled vocabulary in config/reward_categories.yaml."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from bankrec.settings import CONFIG_DIR


@lru_cache(maxsize=1)
def vocabulary(path: Path | None = None) -> dict[str, dict[str, object]]:
    data = yaml.safe_load((path or CONFIG_DIR / "reward_categories.yaml").read_text(encoding="utf-8"))
    return dict(data["categories"])


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern[str], str]]:
    pairs: list[tuple[str, str]] = []
    for code, spec in vocabulary().items():
        synonyms: list[str] = list(spec["synonyms"])  # type: ignore[call-overload]
        for syn in synonyms:
            pairs.append((str(syn), code))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return [(re.compile(r"(?<![\w])" + re.escape(s) + r"(?![\w])", re.IGNORECASE), c) for s, c in pairs]


def category_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, code) of every category mention, longest synonym first, without overlap, in text order."""
    taken: list[tuple[int, int, str]] = []
    for pat, code in _patterns():
        for m in pat.finditer(text):
            if any(s < m.end() and m.start() < e for s, e, _ in taken):
                continue
            taken.append((m.start(), m.end(), code))
    return sorted(taken)


def categories_in(text: str) -> list[str]:
    """Categories mentioned in ``text``, longest synonym first, without overlap. Order of first appearance."""
    seen: list[str] = []
    for _, _, code in category_spans(text):
        if code not in seen:
            seen.append(code)
    return seen


def normalize_category(phrase: str) -> tuple[str, bool]:
    """Map a phrase to one category code. Returns (code, mapped). Unmapped → ("other", False) so the caller
    can route the record to review instead of silently dropping it."""
    cats = categories_in(phrase)
    if not cats:
        return "other", False
    return cats[0], True
