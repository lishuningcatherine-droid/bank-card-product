"""robots.txt parsing and matching per RFC 9309.

Implemented here rather than with ``urllib.robotparser`` because the standard library only supports ``*`` and ``$``
path wildcards from Python 3.13; on 3.12 a rule such as ``Disallow: /*/apply/`` would be silently ignored.

Semantics: the group whose user-agent token is the longest case-insensitive match of our product token is used
(``*`` otherwise; groups with the same token are merged); among matching rules the longest pattern wins, and Allow
wins a tie. ``*`` matches any sequence of characters, a trailing ``$`` anchors the end of the path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote, unquote, urlsplit


@dataclass
class Rules:
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(rx + ("$" if anchored else ""))


def _norm(path: str) -> str:
    # Compare in a canonical percent-encoding so "%7E" and "~" match alike.
    return quote(unquote(path), safe="/*$?=&;:@!+,'()~-._")


class RobotsTxt:
    def __init__(self, groups: dict[str, Rules]) -> None:
        self.groups = groups

    @classmethod
    def parse(cls, text: str) -> RobotsTxt:
        groups: dict[str, Rules] = {}
        current: list[str] = []
        in_agents = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not in_agents:
                    current = []
                current.append(value.lower())
                groups.setdefault(value.lower(), Rules())
                in_agents = True
            elif key in {"allow", "disallow"}:
                in_agents = False
                if not current or (key == "disallow" and value == ""):
                    continue  # rules outside a group are ignored; empty Disallow means allow all
                for agent in current:
                    getattr(groups[agent], key).append(_norm(value))
            else:
                in_agents = False if key != "sitemap" else in_agents
        return cls(groups)

    @classmethod
    def allow_all(cls) -> RobotsTxt:
        return cls({})

    @classmethod
    def disallow_all(cls) -> RobotsTxt:
        return cls({"*": Rules(disallow=["/"])})

    def _rules_for(self, user_agent: str) -> Rules:
        token = re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0].lower()
        best = ""
        for agent in self.groups:
            if agent != "*" and token.startswith(agent) and len(agent) > len(best):
                best = agent
        return self.groups.get(best) or self.groups.get("*") or Rules()

    def can_fetch(self, user_agent: str, url: str) -> bool:
        parts = urlsplit(url)
        path = _norm((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        if path == "/robots.txt":
            return True
        rules = self._rules_for(user_agent)
        best_len, allowed = -1, True
        for is_allow, patterns in ((False, rules.disallow), (True, rules.allow)):
            for p in patterns:
                if _compile(p).match(path):
                    length = len(p)
                    if length > best_len or (length == best_len and is_allow):
                        best_len, allowed = length, is_allow
        return allowed
