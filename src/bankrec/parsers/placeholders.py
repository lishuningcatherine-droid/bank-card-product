"""Detect template placeholders that static HTML shows before client-side rendering (brief §7.2)."""

from __future__ import annotations

import re

_PLACEHOLDER = re.compile(
    r"""^\s*(?:
        NaN%?|undefined|null|N/?A\s*%|
        \$\s*|%|--+%?|—|-\s*%|
        \{\{.*\}\}|\$\{.*\}|\[\[.*\]\]|
        loading\.*|please\ wait\.*
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def is_placeholder(value: str | None) -> bool:
    """True when ``value`` is an empty slot or a render-time template token rather than real data."""
    if value is None:
        return True
    if value.strip() == "":
        return True
    return bool(_PLACEHOLDER.match(value))


_INLINE = re.compile(r"\bNaN\s*%|\{\{[^}]*\}\}|\$\{[^}]*\}|(?<![\w$])\$(?=\s*(?:$|[^\d\s]))", re.IGNORECASE)


def contains_placeholder(text: str) -> bool:
    """True when ``text`` contains an inline placeholder token (e.g. "APY: NaN%", "APR $ variable")."""
    return bool(_INLINE.search(text))
