from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bankrec.recommend.models import OfferView, ProductView


class Page(BaseModel):
    items: list[ProductView]
    total: int
    page: int
    page_size: int


class OfferItem(BaseModel):
    product_id: str
    product_name: str
    bank_name: str
    product_type: str
    offer: OfferView


class OffersPage(BaseModel):
    items: list[OfferItem]
    total: int


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_ids: Annotated[list[Annotated[str, Field(max_length=64)]], Field(min_length=2, max_length=4)]
    max_annual_fee: Annotated[int, Field(ge=0, le=1000)] | None = None
    exclude_over_max_fee: bool = False


class CompareResponse(BaseModel):
    items: list[ProductView]
    excluded: list[dict[str, str]] = Field(default_factory=list)
    rows: list[str]
    disclaimer: str


class HistoryChange(BaseModel):
    field: str
    old: Any = None
    new: Any = None
    change_class: str = Field(alias="class")
    model_config = ConfigDict(populate_by_name=True)


class HistoryEntry(BaseModel):
    kind: Literal["product", "offer"]
    version: int
    date: datetime
    change_class: str
    changes: list[dict[str, Any]]
    source_url: str | None = None


class BankSource(BaseModel):
    bank_id: str
    display_name: str
    official_domains: list[str]
    product_types: dict[str, dict[str, Any]]
    known_limitations: list[str]
    summary: list[dict[str, Any]]
    published_counts: dict[str, dict[str, int]]


class SourcesResponse(BaseModel):
    banks: list[BankSource]
    cross_check_sources: list[dict[str, str]]
    notes: list[str]


class Health(BaseModel):
    status: Literal["ok"]
