from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any

import yaml

from bankrec.settings import CONFIG_DIR


@lru_cache(maxsize=1)
def scoring() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "scoring.yaml").read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def point_values() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "point_values.yaml").read_text(encoding="utf-8")))


def cents_per_point(program: str | None, override: Decimal | None = None) -> tuple[Decimal, str]:
    if override is not None:
        return override, "your adjustment"
    pv = point_values()
    prog = (pv.get("programs") or {}).get(program or "")
    if prog:
        return Decimal(str(prog["cents_per_point"])), str(prog.get("basis", "configured"))
    return Decimal(str(pv["default_cents_per_point"])), "default"
