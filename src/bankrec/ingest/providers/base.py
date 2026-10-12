"""Licensed data providers (DESIGN §21.8): designed, not integrated. No provider ships enabled."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from bankrec.settings import CONFIG_DIR


class ProviderLicense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unconfirmed", "confirmed"]
    confirmed_by: str | None = None
    confirmed_on: date | None = None
    agreement_ref: str | None = None
    display_permitted: bool = False
    attribution_text: str | None = None
    redistribution_permitted: bool = False
    retention_days: int | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str
    display_name: str
    enabled: bool = False
    test_only: bool = False
    credentials_env: list[str] = Field(default_factory=list)
    license: ProviderLicense


class ProviderRecord(BaseModel):
    external_id: str
    bank_id: str
    product_name: str
    product_type: str
    fields: dict[str, Any]
    as_of: datetime


class LicensedProvider(Protocol):
    provider_id: ClassVar[str]

    def fetch_since(self, cursor: str | None) -> Iterator[ProviderRecord]: ...


class ProviderGateError(Exception):
    """A provider may not be enabled without a confirmed license (who and when)."""


def check_gate(cfg: ProviderConfig) -> None:
    if not cfg.enabled:
        return
    lic = cfg.license
    if lic.status != "confirmed" or not lic.confirmed_by or not lic.confirmed_on:
        raise ProviderGateError(
            f"provider {cfg.provider_id!r} is enabled but its license is not confirmed "
            "(status: confirmed, confirmed_by and confirmed_on are all required)"
        )


def load_providers(config_dir: Path = CONFIG_DIR, *, include_test_only: bool = False) -> list[ProviderConfig]:
    out = []
    for p in sorted((config_dir / "providers").glob("*.yaml")):
        cfg = ProviderConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        if cfg.test_only and not include_test_only:
            continue
        check_gate(cfg)
        out.append(cfg)
    return out
