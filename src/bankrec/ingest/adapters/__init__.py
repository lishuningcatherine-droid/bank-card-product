"""Adapter discovery: one module per bank exposing ``Adapter``. No adapter imports another."""

from __future__ import annotations

import importlib
import pkgutil
from functools import cache

from bankrec.ingest.adapters.base import BankAdapter


def adapter_names() -> set[str]:
    import bankrec.ingest.adapters as pkg

    return {m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_")
            and m.name not in {"base", "regulators"}}


@cache
def get_adapter(name: str) -> BankAdapter:
    mod = importlib.import_module(f"bankrec.ingest.adapters.{name}")
    adapter: BankAdapter = mod.Adapter()
    return adapter


def known_parsers() -> set[str]:
    return adapter_names() | {"cfpb_tccp", "cfpb_agreements"}
