"""Capture quality gate (DESIGN §24.18): a degraded capture never proposes removing a value.

A capture is compared with the *baseline*: the snapshot the source's published values came from. Each page section the
baseline shows (product heading, earn rates, fee, APR range, APY) must still be there, and the text must not shrink below
``min_text_ratio`` of the baseline. Otherwise the capture is ``CAPTURE_DEGRADED``: nothing is extracted from it, prod
keeps its values and the source is retried on the next run. A source with no published values has no baseline and
always passes (classification already rejects empty and non-product pages).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from bankrec.settings import CONFIG_DIR

_SECTIONS: dict[str, re.Pattern[str]] = {
    "earn": re.compile(
        r"\b\d{1,2}(?:\.\d{1,2})?\s*(?:%|x\b)\s*(?:total\s+)?(?:cash\s*back|back|points?|miles?|avios|on\b|at\b)",
        re.I,
    ),
    "fee": re.compile(r"\bannual\s+fee\b|\bmonthly\s+(?:service\s+|maintenance\s+)?fee\b", re.I),
    "apr": re.compile(r"\d{1,2}\.\d{2}%\s*(?:to|-|–|—)\s*\d{1,2}\.\d{2}%"),
    "apy": re.compile(r"\bAPY\b"),
}


@lru_cache(maxsize=1)
def quality_policy() -> dict[str, Any]:
    pol = yaml.safe_load((CONFIG_DIR / "validation.yaml").read_text(encoding="utf-8"))
    return dict(pol.get("capture_quality") or {})


def sections(text: str, headings: list[str]) -> dict[str, bool]:
    out = {"product_heading": bool([h for h in headings if h.strip()])}
    out.update({k: bool(p.search(text)) for k, p in _SECTIONS.items()})
    return out


@dataclass
class CaptureQuality:
    sections: dict[str, bool]
    text_len: int
    baseline_len: int | None = None
    missing: list[str] = field(default_factory=list)
    ratio: float | None = None
    score: float = 1.0
    degraded: bool = False

    @property
    def detail(self) -> str:
        parts = []
        if self.missing:
            parts.append("sections missing vs the published capture: " + ", ".join(self.missing))
        if self.ratio is not None:
            parts.append(
                f"text {self.text_len} chars = {self.ratio:.0%} of the published capture ({self.baseline_len})"
            )
        return f"score {self.score:.2f}; " + "; ".join(parts)


def assess(
    text: str, headings: list[str], baseline: tuple[str, list[str]] | None, pol: dict[str, Any] | None = None
) -> CaptureQuality:
    """``baseline`` = (text, headings) of the capture the published values came from, or None."""
    pol = quality_policy() if pol is None else pol
    now = sections(text, headings)
    q = CaptureQuality(sections=now, text_len=len(text))
    if baseline is None:
        return q
    base = sections(*baseline)
    expected = [k for k in pol.get("sections", list(now)) if base.get(k)]
    q.missing = [k for k in expected if not now.get(k)]
    q.baseline_len = len(baseline[0])
    q.ratio = q.text_len / q.baseline_len if q.baseline_len else None
    min_ratio = float(pol.get("min_text_ratio", 0.6))
    kept = (len(expected) - len(q.missing)) / len(expected) if expected else 1.0
    size = min(1.0, (q.ratio or 1.0) / min_ratio)
    q.score = round(kept * size, 2)
    q.degraded = q.score < float(pol.get("min_score", 1.0))
    return q
