"""URL canonicalization and official-domain checks."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAM = re.compile(
    r"^(utm_.*|gclid|gclsrc|dclid|fbclid|msclkid|mc_[ce]id|cid|ref|referr?al.*|aff.*|irgwc|irclickid|"
    r"clickid|campaign.*|source(code)?|promo.*|offer.*code|cmp|icid|iq_id|sc_cid|ranmid|ransiteid|siteid)$",
    re.IGNORECASE,
)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def domain_allowed(url: str, official_domains: list[str]) -> bool:
    """Suffix match on whole labels: "creditcards.chase.com" matches "chase.com"; "chase.com.evil.io" does not."""
    host = host_of(url)
    return any(
        host == d or host.endswith("." + d) for d in (x.lower().lstrip("*.") for x in official_domains)
    )


def disallowed_params(url: str, meaningful: list[str]) -> list[str]:
    keep = {m.lower() for m in meaningful}
    return [k for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True) if k.lower() not in keep]


def canonicalize(url: str, meaningful: list[str] | None = None) -> str:
    """Lowercase scheme/host, drop fragment, keep only allowlisted query params (sorted)."""
    parts = urlsplit(url.strip())
    keep = {m.lower() for m in (meaningful or [])}
    q = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() in keep)
    path = parts.path or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            (parts.hostname or "").lower() + (f":{parts.port}" if parts.port else ""),
            path,
            urlencode(q),
            "",
        )
    )


def looks_like_referral(url: str, patterns: list[str]) -> bool:
    default = [r"/refer(?:ral|-a-friend)?(?:/|$)", r"[?&](?:ref|referral\w*)="]
    return any(re.search(p, url, re.IGNORECASE) for p in default + patterns)
