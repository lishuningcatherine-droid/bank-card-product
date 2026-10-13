"""RFC 9309 robots.txt matching, independent of the Python version (3.12's robotparser ignores wildcards)."""

import pytest

from bankrec.ingest.robots import RobotsTxt

UA = "bankrec/0.1.0 (+https://example.invalid; contact@example.invalid)"
# Synthetic rules modeled on the owner's pre-survey notes (not retrieved from any bank).
ROBOTS = """
User-agent: *
Disallow: /content/dam/chase-ux/ratesheets/
Disallow: /*/apply/
Disallow: /deposits/*.pdf
Disallow: /private$
Allow: /deposits/public.pdf
Disallow: /learn/

User-agent: otherbot
Disallow: /
"""


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/credit-cards/everyday", True),
        ("/content/dam/chase-ux/ratesheets/a.pdf", False),
        ("/us/apply/card", False),  # * wildcard in the middle
        ("/apply/card", True),  # /*/apply/ needs a segment before apply
        ("/deposits/x.pdf", False),  # * wildcard before suffix
        ("/deposits/public.pdf", True),  # longer Allow wins over shorter Disallow
        ("/deposits/x.html", True),
        ("/private", False),  # $ anchor
        ("/private/page", True),
        ("/learn/article", False),
        ("/robots.txt", True),
    ],
)
def test_rfc9309_matching(path: str, allowed: bool) -> None:
    assert RobotsTxt.parse(ROBOTS).can_fetch(UA, f"https://www.examplebank.example{path}") is allowed


def test_group_selection_and_ties() -> None:
    r = RobotsTxt.parse(ROBOTS)
    assert r.can_fetch("otherbot/2.0", "https://x.example/anything") is False
    tie = RobotsTxt.parse("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert tie.can_fetch(UA, "https://x.example/page") is True  # equal length: Allow wins
    specific = RobotsTxt.parse("User-agent: *\nDisallow: /\n\nUser-agent: bankrec\nAllow: /\n")
    assert specific.can_fetch(UA, "https://x.example/a") is True


def test_empty_disallow_and_defaults() -> None:
    assert RobotsTxt.parse("User-agent: *\nDisallow:\n").can_fetch(UA, "https://x.example/a")
    assert RobotsTxt.allow_all().can_fetch(UA, "https://x.example/a")
    assert not RobotsTxt.disallow_all().can_fetch(UA, "https://x.example/a")
    assert RobotsTxt.parse("garbage\n# comment only\n").can_fetch(UA, "https://x.example/a")
