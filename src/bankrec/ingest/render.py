"""Fresh-context Playwright rendering for ``requires_render`` sources (DESIGN §22.1, brief §6.4).

The browser is injected (one per run) so adapters and tests can mock it. Every page gets a brand-new context with no
cookies, no storage state and no login, en-US locale and a U.S. timezone. The page is loaded once; XHR/fetch
responses the page itself loads from official domains are kept as supporting evidence; requests to robots-disallowed
paths are aborted, never fetched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import yaml

from bankrec.failures import Failure
from bankrec.ingest.fetch import FetchResult, HostRateLimiter, RobotsCache
from bankrec.registry.schema import BankConfig, SourceEntry
from bankrec.registry.urls import canonicalize, domain_allowed, looks_like_referral
from bankrec.settings import CONFIG_DIR, Settings

VIEWPORT = {"width": 1280, "height": 900}
MAX_EVIDENCE_BYTES = 200_000


@lru_cache(maxsize=1)
def capture_location() -> dict[str, str]:
    return dict(yaml.safe_load((CONFIG_DIR / "capture_location.yaml").read_text(encoding="utf-8")))


class Renderer:
    def __init__(
        self, settings: Settings, browser: Any, robots: RobotsCache, limiter: HostRateLimiter
    ) -> None:
        self.settings, self.browser, self.robots, self.limiter = settings, browser, robots, limiter

    def _location(self, page: Any, steps: list[dict[str, str]]) -> dict[str, Any]:
        """Enter the capture ZIP in the page's public ZIP form; every step taken is recorded."""
        loc = capture_location()
        done: list[str] = []
        chosen: str | None = None
        for st in steps:
            if "fill" in st:
                page.locator(st["fill"]).first.fill(loc["zip"])
                done.append(f"fill {st['fill']}")
            elif "press" in st:
                page.keyboard.press(st["press"])
                done.append(f"press {st['press']}")
            elif "click" in st:
                page.locator(st["click"]).first.click()
                done.append(f"click {st['click']}")
            elif "select_first" in st:
                sel = page.locator(st["select_first"]).first
                try:
                    sel.wait_for(state="visible", timeout=8_000)
                except Exception:
                    done.append(f"no {st['select_first']} (single county)")
                    continue
                opts = [o for o in sel.locator("option").all() if (o.get_attribute("value") or "").strip()]
                if opts:
                    chosen = opts[0].inner_text().strip()
                    sel.select_option(value=opts[0].get_attribute("value"))
                    done.append(f"select {st['select_first']} = {chosen}")
            elif "wait_for" in st:
                page.wait_for_selector(st["wait_for"], timeout=20_000)
                done.append(f"wait_for {st['wait_for']}")
            elif "wait_ms" in st:
                page.wait_for_timeout(int(st["wait_ms"]))
                done.append(f"wait {st['wait_ms']} ms")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: S110 (pages with constant background requests never go idle)
            pass
        return {"zip": loc["zip"], "label": loc.get("label"), "county": chosen, "steps": done}

    def render(self, source: SourceEntry, bank: BankConfig) -> FetchResult:
        url = canonicalize(str(source.source_url), bank.meaningful_query_params)
        started = datetime.now(UTC)
        blocked = self.robots.check(url)
        if blocked is not None:
            return FetchResult(url, url, None, "", b"", started, failure=blocked, detail="robots.txt")
        self.limiter.wait(urlsplit(url).netloc)
        context = self.browser.new_context(
            storage_state=None,
            locale="en-US",
            timezone_id=bank.capture_timezone,
            user_agent=self.settings.user_agent,
            viewport=VIEWPORT,
            java_script_enabled=True,
        )
        cookies_at_start = len(context.cookies())
        evidence: list[dict[str, Any]] = []
        aborted: list[str] = []

        def on_route(route: Any) -> None:
            req = route.request
            if (
                req.resource_type in {"xhr", "fetch", "document"}
                and domain_allowed(req.url, bank.official_domains)
                and self.robots.check(req.url) is not None
            ):
                aborted.append(req.url)
                route.abort()
                return
            route.continue_()

        def on_response(resp: Any) -> None:
            req = resp.request
            if req.resource_type in {"xhr", "fetch"} and domain_allowed(resp.url, bank.official_domains):
                try:
                    body = resp.body()[:MAX_EVIDENCE_BYTES]
                    evidence.append(
                        {
                            "url": resp.url,
                            "status": resp.status,
                            "content_type": resp.headers.get("content-type", ""),
                            "body": body.decode("utf-8", errors="replace"),
                        }
                    )
                except Exception:  # noqa: S110  (evidence is best-effort)
                    pass

        try:
            context.route("**/*", on_route)
            page = context.new_page()
            page.on("response", on_response)
            # "load", then up to 15 s for network idle: pages with constant background requests (analytics,
            # chat) never go idle, and that alone must not fail the capture. What was reached is recorded.
            resp = page.goto(url, wait_until="load", timeout=45_000)
            waited = "load"
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
                waited += "+networkidle"
            except Exception:
                waited += "+networkidle_not_reached_15s"
            if source.render_ready_selector:
                page.wait_for_selector(source.render_ready_selector, timeout=15_000)
                waited += f"+selector:{source.render_ready_selector}"
            clicked = []
            for sel in source.expand_selectors:
                loc = page.locator(sel)
                if loc.count():
                    loc.first.click()
                    clicked.append(sel)
            location = self._location(page, source.location_steps) if source.location_steps else None
            html = page.content()
            final = page.url
            status = resp.status if resp is not None else None
            chain: list[str] = []
            r = resp.request if resp is not None else None
            while r is not None and r.redirected_from is not None:
                r = r.redirected_from
                chain.insert(0, r.url)
            browser_version = self.browser.version
        except Exception as e:
            context.close()
            msg = str(e)
            f = (
                Failure.TIMEOUT
                if "Timeout" in msg
                else (
                    Failure.ENV_NETWORK_BLOCKED
                    if any(
                        k in msg for k in ("ERR_TUNNEL", "ERR_PROXY", "ERR_NAME", "ERR_INTERNET_DISCONNECTED")
                    )
                    else Failure.HTTP_ERROR
                )
            )
            return FetchResult(url, url, None, "", b"", started, failure=f, detail=msg[:300])
        context.close()
        now = datetime.now(UTC)
        conditions = {
            "capture_context": "public_default",
            "method": "playwright",
            "context_fresh": True,
            "cookies_at_start": cookies_at_start,
            "storage_state": None,
            "login": False,
            "locale": "en-US",
            "timezone_id": bank.capture_timezone,
            "viewport": VIEWPORT,
            "user_agent": self.settings.user_agent,
            "url_canonical": url,
            "url_final": final,
            "redirect_chain": chain,
            "render_wait": {"strategy": waited},
            "expanders_clicked": clicked,
            **({"location": location} if location else {}),
            "aborted_robots_disallowed": aborted,
            "captured_at": now.isoformat(),
            "browser": f"chromium {browser_version}",
            "runner_label": self.settings.capture_runner_label,
        }
        res = FetchResult(
            url,
            final,
            status,
            "text/html; charset=utf-8",
            html.encode("utf-8"),
            now,
            chain,
            capture_conditions=conditions,
            supporting_responses=evidence,
        )
        if not domain_allowed(final, bank.official_domains):
            res.failure, res.detail = Failure.REDIRECT_OFF_DOMAIN, f"redirected to {final}"
        elif looks_like_referral(final, bank.referral_url_patterns):
            conditions["capture_anomaly"] = "redirected_to_referral_or_tracking_url"
        return res
