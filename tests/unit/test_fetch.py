"""Responsible retrieval: robots, rate limit, backoff, honest UA, no persistent cookies, block recording."""

from pathlib import Path

import httpx
import pytest

from bankrec.failures import Failure
from bankrec.ingest.fetch import Fetcher, FixtureFetcher, HostRateLimiter
from bankrec.registry.schema import BankConfig, SourceEntry
from bankrec.settings import Settings

BANK = BankConfig(
    bank_id="example_bank",
    display_name="Example Bank",
    official_domains=["examplebank.example"],
    adapter="example_bank",
    test_only=True,
)
# Synthetic robots.txt modeled on the owner's pre-survey description of Chase/Amex/BoA rules (not retrieved).
ROBOTS = "User-agent: *\nDisallow: /content/dam/chase-ux/ratesheets/\nDisallow: /*/apply/\nDisallow: /deposits/*.pdf\n"


def src(path: str = "/credit-cards/x", **kw) -> SourceEntry:  # type: ignore[no-untyped-def]
    return SourceEntry(
        bank_id="example_bank",
        slug="x",
        product_type="credit_card",
        source_url=f"https://www.examplebank.example{path}",
        source_kind="product_detail",
        parser_name="example_bank",
        expected_entity="X",
        **kw,
    )


def settings() -> Settings:
    return Settings(BANKREC_MIN_HOST_INTERVAL_S=3, BANKREC_CONTACT_EMAIL="ops@example.invalid")


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def make(handler, clock: Clock | None = None) -> tuple[Fetcher, list[httpx.Request]]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return handler(req)

    c = clock or Clock()
    f = Fetcher(settings(), transport=httpx.MockTransport(h), sleep=c.sleep)
    f.limiter = HostRateLimiter(3, clock=c.now, sleep=c.sleep)
    f.robots.limiter = f.limiter
    return f, seen


def test_honest_user_agent_and_success() -> None:
    f, seen = make(lambda r: httpx.Response(200, html="<h1>X</h1>", headers={"set-cookie": "a=1"}))
    res = f.fetch(src(), BANK)
    assert res.failure is None and res.status == 200
    ua = seen[-1].headers["user-agent"]
    assert ua.startswith("bankrec/") and "ops@example.invalid" in ua
    f.fetch(src("/credit-cards/y"), BANK)
    assert "cookie" not in seen[-1].headers  # no cookie carried between pages


@pytest.mark.parametrize(
    "path", ["/content/dam/chase-ux/ratesheets/a.pdf", "/us/apply/card", "/deposits/x.pdf"]
)
def test_robots_disallowed_paths_are_never_fetched(path: str) -> None:
    f, seen = make(lambda r: httpx.Response(200, html="ok"))
    res = f.fetch(src(path), BANK)
    assert res.failure is Failure.ROBOTS_DISALLOWED
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_robots_unreachable_means_unreachable() -> None:
    def h(req: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("CONNECT tunnel failed, response 403")

    f = Fetcher(settings(), transport=httpx.MockTransport(h), sleep=lambda s: None)
    res = f.fetch(src(), BANK)
    assert res.failure is Failure.ENV_NETWORK_BLOCKED


def test_rate_limit_three_seconds_per_host() -> None:
    clock = Clock()
    f, _ = make(lambda r: httpx.Response(200, html="ok"), clock)
    f.fetch(src("/a"), BANK)
    f.fetch(src("/b"), BANK)
    assert clock.sleeps and all(abs(s - 3.0) < 1e-9 for s in clock.sleeps)


def test_backoff_on_429_then_success() -> None:
    calls = {"n": 0}

    def h(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] < 2 else httpx.Response(200, html="ok")

    clock = Clock()
    f, _ = make(h, clock)
    res = f.fetch(src(), BANK)
    assert res.status == 200 and res.attempts == 2 and any(s >= 3 for s in clock.sleeps)


def test_gives_up_after_max_attempts_and_records() -> None:
    f, _ = make(lambda r: httpx.Response(503))
    res = f.fetch(src(), BANK)
    assert res.status == 503 and res.attempts == 3


def test_tracking_params_stripped_and_off_domain_redirect() -> None:
    f, seen = make(lambda r: httpx.Response(200, html="ok"))
    f.fetch(src("/credit-cards/x?utm_source=a&gclid=b"), BANK)
    assert seen[-1].url.query == b""

    def redirect(req: httpx.Request) -> httpx.Response:
        if req.url.host == "www.examplebank.example":
            return httpx.Response(302, headers={"location": "https://other.example.net/x"})
        return httpx.Response(200, html="ok")

    f2, _ = make(redirect)
    res = f2.fetch(src(), BANK)
    assert res.failure is Failure.REDIRECT_OFF_DOMAIN


def test_fixture_fetcher_only_for_test_banks(tmp_path: Path) -> None:
    (tmp_path / "p.html").write_text("<h1>x</h1>")
    ff = FixtureFetcher(settings(), tmp_path)
    ok = ff.fetch(src(fixture_path="p.html"), BANK)
    assert ok.status == 200 and ok.capture_conditions["context_fresh"] is True
    real = BANK.model_copy(update={"test_only": False})
    assert ff.fetch(src(fixture_path="p.html"), real).failure is Failure.ENV_NETWORK_BLOCKED
