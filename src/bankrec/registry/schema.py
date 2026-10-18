"""Pydantic schemas for config/banks/*.yaml and config/sources/*.yaml."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from bankrec.model import ProductType, SourceKind

Availability = Literal["offered", "not_offered", "unknown"]
Tier = Literal["apy", "offer", "terms", "regulator_release"]


class TypeAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability: Availability
    evidence_url: HttpUrl | None = None
    note: str | None = None


class Discovery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robots_url: HttpUrl | None = None
    sitemaps: list[HttpUrl] = Field(default_factory=list)
    sitemap_url_patterns: dict[str, list[str]] = Field(default_factory=dict)  # product_type -> regexes


class BankConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_id: str
    display_name: str
    role: Literal["bank", "regulator"] = "bank"
    official_domains: list[str] = Field(min_length=1)
    product_types: dict[ProductType, TypeAvailability] = Field(default_factory=dict)
    adapter: str
    test_only: bool = False
    capture_timezone: str = "America/New_York"
    meaningful_query_params: list[str] = Field(default_factory=list)
    referral_url_patterns: list[str] = Field(default_factory=list)
    block_signatures: list[str] = Field(default_factory=list)
    boilerplate_phrases: list[str] = Field(default_factory=list)
    # Elements that hold the product name when the page's h1 is a promotion (classifier "product heading" signal).
    product_heading_selectors: list[str] = Field(default_factory=list)
    cfpb_issuer_names: list[str] = Field(default_factory=list)
    discovery: Discovery = Field(default_factory=Discovery)
    known_limitations: list[str] = Field(default_factory=list)

    @field_validator("bank_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", v):
            raise ValueError("bank_id must be a lowercase slug")
        return v


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_id: str
    slug: str
    product_type: ProductType | None = None
    source_url: HttpUrl
    source_kind: SourceKind
    parser_name: str
    requires_render: bool = False
    enabled: bool = True
    priority: int = 50
    expected_entity: str
    notes: str | None = None
    state: Literal["curated", "discovered", "disabled"] = "curated"
    refresh_tier: Tier | None = None
    has_offers: bool = False
    render_ready_selector: str | None = None
    expand_selectors: list[str] = Field(default_factory=list)
    # Pages whose rates depend on location: steps that enter the capture ZIP in the page's own public ZIP form
    # (config/capture_location.yaml; owner decision 2026-10-18). Each step is one of {fill: css} (types the ZIP),
    # {press: key}, {click: css}, {select_first: css} (first non-empty option), {wait_for: css}, {wait_ms: n}.
    location_steps: list[dict[str, str]] = Field(default_factory=list)
    retrieved_by_user_on: str | None = None
    fixture_path: str | None = (
        None  # test_only banks only: served by the fixture transport instead of the network
    )

    @property
    def source_id(self) -> str:
        return f"{self.bank_id}:{self.slug}"

    @property
    def tier(self) -> str:
        if self.refresh_tier:
            return self.refresh_tier
        if self.source_kind is SourceKind.regulator_dataset:
            return "regulator_release"
        if self.product_type is ProductType.savings and self.source_kind is SourceKind.product_detail:
            return "apy"
        if self.source_kind is SourceKind.offer_detail or self.has_offers:
            return "offer"
        return "terms"


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_id: str
    sources: list[SourceEntry] = Field(default_factory=list)
