"""Small card-page readers shared by the adapters added for the offer tracker (Citi, Discover, Wells Fargo).

Each returns text exactly as the page states it (so the provenance guard can locate it) or values parsed from such
text; nothing is inferred.
"""

from __future__ import annotations

import re
from decimal import Decimal

_TILE_RATE = re.compile(
    r"^\d{1,2}(?:\.\d{1,2})?\s*(?:%|[xX])(?:\s+(?:cash back|points|miles|cash rewards))?$"
)
_FOOTNOTE_TAIL = re.compile(r"(?<=[A-Za-z.)])[\d†‡*¹²³]+$")
_APR_RANGE = re.compile(
    r"(\d{1,2}\.\d{2})%\s*(?:to|-|–)\s*(\d{1,2}\.\d{2})%\s+variable APR"
    # Wells Fargo: "18.74%, 24.74% or 28.74% variable APR"
    r"|(\d{1,2}\.\d{2})%(?:,\s*\d{1,2}\.\d{2}%)*,?\s+or\s+(\d{1,2}\.\d{2})%\s+variable APR",
    re.IGNORECASE,
)
_APR_AFTER = re.compile(
    r"variable APR (?:will be|is) (\d{1,2}\.\d{2})%(?:,\s*\d{1,2}\.\d{2}%)*,?\s+(?:or|to)\s+(\d{1,2}\.\d{2})%",
    re.IGNORECASE,
)


def strip_footnote(s: str) -> str:
    """ "on restaurants2" → "on restaurants" (a trailing footnote marker glued to the last word)."""
    return _FOOTNOTE_TAIL.sub("", s.strip()).strip()


def tile_statements(lines: list[str]) -> list[str]:
    """Earn tiles stated as a rate line followed by its label ("3X" / "on restaurants2") → "3X on restaurants".
    The result is a substring of the page's whitespace-normalised text, so it can be located as evidence."""
    out: list[str] = []
    clean = [ln.strip() for ln in lines if ln.strip()]
    for i, ln in enumerate(clean[:-1]):
        nxt = clean[i + 1]
        if _TILE_RATE.match(ln) and re.match(r"^on\s+\w", nxt, re.IGNORECASE) and len(nxt) <= 80:
            out.append(f"{ln} {strip_footnote(nxt)}")
    return out


def apr_range(text: str) -> tuple[Decimal, Decimal, str] | None:
    """The purchase APR range and the sentence stating it, as the page states it."""
    for sentence in re.split(r"(?<=[.;])\s+", text):
        m = _APR_RANGE.search(sentence) or _APR_AFTER.search(sentence)
        if m:
            nums = [g for g in m.groups() if g]
            return Decimal(nums[0]), Decimal(nums[-1]), sentence.strip()
    return None
