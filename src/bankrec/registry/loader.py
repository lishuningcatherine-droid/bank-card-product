"""Load and validate the YAML registry. Fails loudly (brief §6.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from bankrec.model import SourceKind
from bankrec.registry.schema import BankConfig, SourceEntry, SourcesFile
from bankrec.registry.urls import canonicalize, disallowed_params, domain_allowed, looks_like_referral
from bankrec.settings import CONFIG_DIR


class RegistryError(Exception):
    """Malformed, duplicate, or non-official registry content."""


class EmptyRegistryError(RegistryError):
    """No enabled sources. Never a silent zero-record run."""


@dataclass
class Registry:
    banks: dict[str, BankConfig]
    sources: list[SourceEntry]
    warnings: list[str] = field(default_factory=list)
    banks_without_sources: list[str] = field(default_factory=list)

    def enabled(self, tier: str | None = None, bank: str | None = None) -> list[SourceEntry]:
        return [s for s in self.sources
                if s.enabled and s.state == "curated" and (tier is None or s.tier == tier)
                and (bank is None or s.bank_id == bank)]

    def bank(self, bank_id: str) -> BankConfig:
        return self.banks[bank_id]


def _read_yaml(path: Path) -> object:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RegistryError(f"{path}: malformed YAML: {e}") from e
    if data is None:
        raise RegistryError(f"{path}: file is empty")
    return data


def load_registry(config_dir: Path = CONFIG_DIR, *, include_test_only: bool = False,
                  known_parsers: set[str] | None = None, require_sources: bool = True) -> Registry:
    banks_dir, sources_dir = config_dir / "banks", config_dir / "sources"
    banks: dict[str, BankConfig] = {}
    for p in sorted(banks_dir.glob("*.yaml")):
        if p.name.startswith("_") or p.name.endswith(".rules.yaml"):
            continue
        try:
            b = BankConfig.model_validate(_read_yaml(p))
        except ValidationError as e:
            raise RegistryError(f"{p}: {e}") from e
        if b.bank_id != p.stem:
            raise RegistryError(f"{p}: bank_id {b.bank_id!r} must match file name")
        if b.test_only and not include_test_only:
            continue
        banks[b.bank_id] = b
    if not banks:
        raise EmptyRegistryError(f"no bank configs in {banks_dir}")

    sources: list[SourceEntry] = []
    seen_ids: set[str] = set()
    seen_urls: set[tuple[str, str]] = set()
    errors: list[str] = []
    for p in sorted(sources_dir.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        try:
            sf = SourcesFile.model_validate(_read_yaml(p))
        except (ValidationError, RegistryError) as e:
            raise RegistryError(f"{p}: {e}") from e
        if sf.bank_id not in banks:
            continue  # test_only bank excluded, or bank config missing (checked below)
        if sf.bank_id != p.stem.removesuffix(".discovered"):
            raise RegistryError(f"{p}: bank_id {sf.bank_id!r} must match file name")
        bank = banks[sf.bank_id]
        for s in sf.sources:
            url = str(s.source_url)
            where = f"{p.name}:{s.slug}"
            if s.bank_id != sf.bank_id:
                errors.append(f"{where}: bank_id mismatch")
            if not url.startswith("https://"):
                errors.append(f"{where}: source_url must be https")
            if not domain_allowed(url, bank.official_domains):
                errors.append(f"{where}: {url} is not on an official domain {bank.official_domains}")
            bad = disallowed_params(url, bank.meaningful_query_params)
            if bad:
                errors.append(f"{where}: tracking/non-allowlisted query params {bad} (use the canonical URL)")
            if looks_like_referral(url, bank.referral_url_patterns):
                errors.append(f"{where}: referral URL is not allowed")
            if s.source_id in seen_ids:
                errors.append(f"{where}: duplicate slug")
            key = (s.bank_id, canonicalize(url, bank.meaningful_query_params))
            if key in seen_urls:
                errors.append(f"{where}: duplicate URL {url}")
            seen_ids.add(s.source_id)
            seen_urls.add(key)
            if s.state == "discovered" and s.enabled:
                errors.append(f"{where}: discovered sources are never auto-enabled")
            if known_parsers is not None and s.parser_name not in known_parsers:
                errors.append(f"{where}: unknown parser {s.parser_name!r}")
            if s.fixture_path and not bank.test_only:
                errors.append(f"{where}: fixture_path is only allowed for test_only banks")
            if s.source_kind is not SourceKind.regulator_dataset and s.product_type is None:
                errors.append(f"{where}: product_type is required")
            if (s.has_offers or s.source_kind is SourceKind.offer_detail) and not s.requires_render:
                # Public-offer capture always renders in a fresh context (DESIGN §22.1).
                s.requires_render = True
            sources.append(s)
    if errors:
        raise RegistryError("registry validation failed:\n  " + "\n  ".join(errors))

    reg = Registry(banks=banks, sources=sources)
    product_banks = [b for b in banks.values() if b.role == "bank"]
    reg.banks_without_sources = sorted(b.bank_id for b in product_banks if not reg.enabled(bank=b.bank_id))
    if require_sources and not reg.enabled():
        raise EmptyRegistryError(
            "registry has no enabled sources; refusing a silent zero-record run. Banks without sources: "
            + ", ".join(reg.banks_without_sources))
    return reg
