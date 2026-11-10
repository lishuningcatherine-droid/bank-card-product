"""Tracker configuration (config/tracker/*.yaml)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bankrec.settings import CONFIG_DIR

DIR = CONFIG_DIR / "tracker"


def _load(name: str) -> dict[str, Any]:
    return dict(yaml.safe_load((DIR / f"{name}.yaml").read_text(encoding="utf-8")) or {})


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    return _load("settings")


@lru_cache(maxsize=1)
def cards() -> list[dict[str, Any]]:
    """The tracked cards. E2E tests point BANKREC_TRACKER_CARDS_FILE at fictional Example Bank cards; that override
    is refused in production."""
    override = os.environ.get("BANKREC_TRACKER_CARDS_FILE")
    if override:
        if os.environ.get("BANKREC_ENV") == "prod":
            raise RuntimeError(
                "BANKREC_TRACKER_CARDS_FILE is for tests only and is refused when BANKREC_ENV=prod"
            )
        data = yaml.safe_load(Path(override).read_text(encoding="utf-8")) or {}
        return list(data.get("cards", []))
    return list(_load("cards").get("cards", []))


@lru_cache(maxsize=1)
def manual_only() -> list[dict[str, Any]]:
    return list(_load("cards").get("manual_only", []))


@lru_cache(maxsize=1)
def rules() -> list[dict[str, Any]]:
    return list(_load("rules").get("rules", []))


@lru_cache(maxsize=1)
def programs() -> dict[str, dict[str, Any]]:
    return dict(_load("valuation").get("programs", {}))
