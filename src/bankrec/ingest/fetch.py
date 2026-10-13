"""Responsible retrieval (brief §2, §6.4).

* robots.txt is obeyed for every path, including XHR/fetch paths a rendered page loads;
* at most one request per host every ``min_host_interval_s`` (default 3 s), exponential backoff on 429/5xx/timeouts;
* an honest User-Agent with the configured contact address;
* no proxies, no stealth, no CAPTCHA/login/paywall workarounds. A blocked fetch is recorded, never bypassed.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from bankrec.failures import Failure
from bankrec.ingest.robots import RobotsTxt
from bankrec.registry.schema import BankConfig, SourceEntry
from bankrec.registry.urls import canonicalize, domain_allowed, looks_like_referral
from bankrec.settings import Settings


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    content_type: str
    body: bytes
    retrieved_at: datetime
    redirect_chain: list[str] = field(default_factory=list)
    capture_method: str = "automated"
    capture_conditions: dict[str, Any] = field(default_factory=dict)
    supporting_responses: list[dict[str, Any]] = field(default_factory=list)
    failure: Failure | None = None
    detail: str = ""
    attempts: int = 1


class HostRateLimiter:
    def __init__(
        self,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval_s
        self.clock, self.sleep = clock, sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delta = self.clock() - last
            if delta < self.min_interval:
                self.sleep(self.min_interval - delta)
        self._last[host] = self.clock()


class RobotsCache:
    """Per-run robots.txt cache. Unreachable robots.txt → the host is treated as unreachable (never as allowed)."""

    def __init__(self, client: httpx.Client, limiter: HostRateLimiter, user_agent: str) -> None:
        self.client, self.limiter, self.ua = client, limiter, user_agent
        self._cache: dict[str, RobotsTxt | Failure] = {}

    def check(self, url: str) -> Failure | None:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._cache:
            self._cache[host] = self._load(host)
        rp = self._cache[host]
        if isinstance(rp, Failure):
            return rp
        return None if rp.can_fetch(self.ua, url) else Failure.ROBOTS_DISALLOWED

    def _load(self, host: str) -> RobotsTxt | Failure:
        self.limiter.wait(urlsplit(host).netloc)
        try:
            r = self.client.get(host + "/robots.txt")
        except httpx.ProxyError:
            return Failure.ENV_NETWORK_BLOCKED
        except httpx.TimeoutException:
            return Failure.TIMEOUT
        except httpx.HTTPError:
            return Failure.ENV_NETWORK_BLOCKED
        if r.status_code in (401, 403):
            return RobotsTxt.disallow_all()
        if r.status_code >= 400:
            return RobotsTxt.allow_all()  # no robots.txt: standard semantics (RFC 9309 §2.3.1.3)
        return RobotsTxt.parse(r.text)


def _classify_exception(e: Exception) -> Failure:
    if isinstance(e, httpx.ProxyError):
        return Failure.ENV_NETWORK_BLOCKED
    if isinstance(e, httpx.TimeoutException):
        return Failure.TIMEOUT
    msg = str(e)
    if "CONNECT" in msg or "403" in msg or "Name or service not known" in msg:
        return Failure.ENV_NETWORK_BLOCKED
    return Failure.HTTP_ERROR


class Fetcher:
    """Plain HTTP retrieval with robots, rate limiting and backoff. One instance per run."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        self.settings = settings
        self.limiter = HostRateLimiter(settings.min_host_interval_s, sleep=sleep)
        self.sleep = sleep
        self.max_attempts = max_attempts
        # A fresh client per run with no persistent cookie jar between pages (cookies are cleared per request).
        self.client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30.0,
            transport=transport,
        )
        self.robots = RobotsCache(self.client, self.limiter, settings.user_agent)

    def close(self) -> None:
        self.client.close()

    def fetch(self, source: SourceEntry, bank: BankConfig) -> FetchResult:
        url = canonicalize(str(source.source_url), bank.meaningful_query_params)
        now = datetime.now(UTC)
        blocked = self.robots.check(url)
        if blocked is not None:
            return FetchResult(
                url,
                url,
                None,
                "",
                b"",
                now,
                failure=blocked,
                detail="robots.txt disallows this path"
                if blocked is Failure.ROBOTS_DISALLOWED
                else "robots.txt unreachable",
            )
        host = urlsplit(url).netloc
        attempt, delay = 0, max(self.settings.min_host_interval_s, 1.0)
        while True:
            attempt += 1
            self.limiter.wait(host)
            self.client.cookies.clear()
            try:
                r = self.client.get(url)
            except Exception as e:  # network-level failure
                f = _classify_exception(e)
                if f is Failure.TIMEOUT and attempt < self.max_attempts:
                    self.sleep(delay + random.uniform(0, 1))  # noqa: S311
                    delay *= 2
                    continue
                return FetchResult(
                    url,
                    url,
                    None,
                    "",
                    b"",
                    datetime.now(UTC),
                    failure=f,
                    detail=str(e)[:300],
                    attempts=attempt,
                )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.max_attempts:
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else delay
                self.sleep(wait + random.uniform(0, 1))  # noqa: S311
                delay *= 2
                continue
            chain = [str(h.url) for h in r.history]
            final = str(r.url)
            res = FetchResult(
                url,
                final,
                r.status_code,
                r.headers.get("content-type", ""),
                r.content,
                datetime.now(UTC),
                chain,
                attempts=attempt,
                capture_conditions={
                    "capture_context": "public_default",
                    "method": "http",
                    "cookies_at_start": 0,
                    "login": False,
                    "user_agent": self.settings.user_agent,
                    "url_canonical": url,
                    "url_final": final,
                    "redirect_chain": chain,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "runner_label": self.settings.capture_runner_label,
                },
            )
            if not domain_allowed(final, bank.official_domains):
                res.failure, res.detail = Failure.REDIRECT_OFF_DOMAIN, f"redirected to {final}"
            elif looks_like_referral(final, bank.referral_url_patterns) or (
                canonicalize(final, bank.meaningful_query_params) != final.split("#")[0] and chain
            ):
                res.capture_conditions["capture_anomaly"] = "redirected_to_referral_or_tracking_url"
            return res


class FixtureFetcher:
    """Serves ``fixture_path`` files for test_only banks through the same pipeline (no network)."""

    def __init__(self, settings: Settings, repo_root: Path) -> None:
        self.settings, self.root = settings, repo_root

    def close(self) -> None:
        pass

    def fetch(self, source: SourceEntry, bank: BankConfig) -> FetchResult:
        if not bank.test_only or not source.fixture_path:
            return FetchResult(
                str(source.source_url),
                str(source.source_url),
                None,
                "",
                b"",
                datetime.now(UTC),
                failure=Failure.ENV_NETWORK_BLOCKED,
                detail="fixture fetcher used for a non-test source",
            )
        url = canonicalize(str(source.source_url), bank.meaningful_query_params)
        path = self.root / source.fixture_path
        body = path.read_bytes()
        ctype = "application/pdf" if path.suffix == ".pdf" else "text/html; charset=utf-8"
        now = datetime.now(UTC)
        return FetchResult(
            url,
            url,
            200,
            ctype,
            body,
            now,
            capture_method="fixture",
            capture_conditions={
                "capture_context": "public_default",
                "method": "fixture",
                "context_fresh": True,
                "cookies_at_start": 0,
                "storage_state": None,
                "login": False,
                "locale": "en-US",
                "timezone_id": bank.capture_timezone,
                "url_canonical": url,
                "url_final": url,
                "captured_at": now.isoformat(),
                "runner_label": self.settings.capture_runner_label,
                "fixture_path": source.fixture_path,
            },
        )
