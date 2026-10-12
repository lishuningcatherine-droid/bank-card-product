"""HTTP hardening: request IDs, JSON access logs without bodies, size limits, POST rate limiting, headers."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("bankrec.api.access")
MAX_BODY_BYTES = 16 * 1024


def problem(status: int, title: str, detail: str = "") -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        media_type="application/problem+json",
    )


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status and latency. Never the body; never query strings of POST requests."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length is None:
                return problem(411, "Length required")
            if not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return problem(413, "Request too large", f"Maximum {MAX_BODY_BYTES} bytes.")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit on POST requests per client address (in-process; one API replica in v1)."""

    def __init__(self, app: object, per_minute: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST":
            key = request.client.host if request.client else "unknown"
            now = time.monotonic()
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                r = problem(429, "Too many requests", "Please wait a minute and try again.")
                r.headers["Retry-After"] = "60"
                return r
            q.append(now)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        if request.method == "POST":
            h["Cache-Control"] = "no-store"
        if self.hsts:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
