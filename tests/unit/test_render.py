"""Fresh-context public-offer capture against a LOCAL server (no external network)."""

import http.server
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from bankrec.ingest.fetch import HostRateLimiter, RobotsCache
from bankrec.ingest.render import Renderer
from bankrec.registry.schema import BankConfig, SourceEntry
from bankrec.settings import Settings

# An empty value means "unset" (Path("") would resolve to the current directory).
CHROME = os.environ.get("BANKREC_CHROMIUM_EXECUTABLE") or "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
pytestmark = pytest.mark.browser

PAGE = """<!doctype html><html><body><h1>Example Bank Test Card</h1>
<p id="lang"></p><p id="tz"></p><p id="cookie"></p><p id="offer">loading</p>
<script>
document.getElementById('lang').textContent = navigator.language;
document.getElementById('tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
document.getElementById('cookie').textContent = 'cookie:' + document.cookie;
fetch('/api/offer').then(r => r.json()).then(j => document.getElementById('offer').textContent = j.text);
fetch('/private/blocked').catch(() => {});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    cookies_seen: list[str] = []
    paths: list[str] = []

    def log_message(self, *a: object) -> None:
        pass

    def do_GET(self) -> None:
        type(self).paths.append(self.path)
        type(self).cookies_seen.append(self.headers.get("Cookie", ""))
        if self.path == "/robots.txt":
            body, ctype = b"User-agent: *\nDisallow: /private/\n", "text/plain"
        elif self.path == "/api/offer":
            body, ctype = b'{"text": "Earn up to 50,000 bonus points"}', "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if self.path == "/api/offer":
            self.send_header("Set-Cookie", "visitor=returning; Path=/")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[str]:
    Handler.cookies_seen, Handler.paths = [], []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def browser() -> Iterator[object]:
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=CHROME) if Path(CHROME).exists() else p.chromium.launch()
        except Error as e:
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


def test_fresh_context_locale_timezone_and_xhr_evidence(server: str, browser: object) -> None:
    import httpx

    bank = BankConfig(
        bank_id="example_bank",
        display_name="Example Bank",
        official_domains=["127.0.0.1"],
        adapter="example_bank",
        test_only=True,
    )
    st = Settings(BANKREC_MIN_HOST_INTERVAL_S=0)
    lim = HostRateLimiter(0)
    client = httpx.Client()
    robots = RobotsCache(client, lim, st.user_agent)
    r = Renderer(st, browser, robots, lim)
    src = SourceEntry(
        bank_id="example_bank",
        slug="t",
        product_type="credit_card",
        source_url=f"{server.replace('http', 'https', 0)}/card",
        source_kind="offer_detail",
        parser_name="example_bank",
        expected_entity="Example Bank Test Card",
    )
    # SourceEntry requires https; render against the local http server by overriding the URL afterwards.
    object.__setattr__(src, "source_url", f"{server}/card?utm_source=x")
    first = r.render(src, bank)
    second = r.render(src, bank)
    for res in (first, second):
        html = res.body.decode()
        assert res.failure is None
        assert ">en-US<" in html and ">America/New_York<" in html
        assert 'id="cookie">cookie:</p>' in html  # no cookie from a previous visit at load time
        cc = res.capture_conditions
        assert cc["context_fresh"] is True and cc["cookies_at_start"] == 0 and cc["login"] is False
        assert cc["url_canonical"].endswith("/card")  # tracking params stripped
        assert "Earn up to 50,000 bonus points" in html
        assert any(e["url"].endswith("/api/offer") for e in res.supporting_responses)
        assert any(u.endswith("/private/blocked") for u in cc["aborted_robots_disallowed"])
    # The server set a cookie on the first visit; the second page load must not send it back.
    page_loads = [c for p, c in zip(Handler.paths, Handler.cookies_seen, strict=True) if p == "/card"]
    assert page_loads == ["", ""]
    assert "/private/blocked" not in Handler.paths
