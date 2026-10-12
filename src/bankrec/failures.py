"""Closed failure taxonomy used by reports, logs, and tests (brief §7.6)."""

from __future__ import annotations

from enum import StrEnum


class Failure(StrEnum):
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    ENV_NETWORK_BLOCKED = "ENV_NETWORK_BLOCKED"
    HTTP_ERROR = "HTTP_ERROR"
    HTTP_BLOCKED = "HTTP_BLOCKED"
    BOT_CHALLENGE = "BOT_CHALLENGE"
    TIMEOUT = "TIMEOUT"
    REDIRECT_OFF_DOMAIN = "REDIRECT_OFF_DOMAIN"
    EMPTY_PAGE = "EMPTY_PAGE"
    LOGIN_WALL = "LOGIN_WALL"
    PLACEHOLDER_VALUE = "PLACEHOLDER_VALUE"
    NON_PRODUCT_PAGE = "NON_PRODUCT_PAGE"
    PARSE_ERROR = "PARSE_ERROR"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONFLICT = "CONFLICT"
    STALE = "STALE"


NEXT_ACTION: dict[Failure, str] = {
    Failure.ROBOTS_DISALLOWED: "manual capture (robots.txt disallows automated retrieval)",
    Failure.ENV_NETWORK_BLOCKED: "allow the domain in the environment network policy, run locally, or manual capture",
    Failure.HTTP_ERROR: "check URL; update registry if the page moved",
    Failure.HTTP_BLOCKED: "manual capture",
    Failure.BOT_CHALLENGE: "manual capture (never bypass)",
    Failure.TIMEOUT: "retry next scheduled run; manual capture if persistent",
    Failure.REDIRECT_OFF_DOMAIN: "update URL in registry",
    Failure.EMPTY_PAGE: "set requires_render or manual capture",
    Failure.LOGIN_WALL: "remove source (login pages are out of scope)",
    Failure.PLACEHOLDER_VALUE: "set requires_render or manual capture",
    Failure.NON_PRODUCT_PAGE: "update URL to an official product-detail page",
    Failure.PARSE_ERROR: "fix parser selector",
    Failure.SCHEMA_DRIFT: "update adapter rules for the changed page structure",
    Failure.VALIDATION_FAILED: "review extracted values",
    Failure.CONFLICT: "bankrec review show <id>",
    Failure.STALE: "re-run ingestion for this tier",
}
