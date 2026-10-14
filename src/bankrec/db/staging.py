"""Pipeline, provenance, review, and history tables (schema ``staging``). Never read by the public API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from bankrec.db.base import StagingBase

J = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class SourceRegistry(StagingBase):
    __tablename__ = "source_registry"
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    bank_id: Mapped[str] = mapped_column(String(64), index=True)
    product_type: Mapped[str | None] = mapped_column(String(20))
    source_url: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(30))
    parser_name: Mapped[str] = mapped_column(Text)
    requires_render: Mapped[bool] = mapped_column(Boolean)
    enabled: Mapped[bool] = mapped_column(Boolean)
    priority: Mapped[int] = mapped_column(Integer)
    expected_entity: Mapped[str] = mapped_column(Text)
    refresh_tier: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(12))
    test_only: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(J, default=dict)


class SourcePage(StagingBase):
    __tablename__ = "source_pages"
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_parse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_content_sha256: Mapped[str | None] = mapped_column(String(64))
    last_parser_version: Mapped[str | None] = mapped_column(Text)
    last_snapshot_id: Mapped[str | None] = mapped_column(Text)
    last_found_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    last_offer_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    health: Mapped[str] = mapped_column(String(10), default="new")  # new | healthy | degraded | failing


class ScrapeRun(StagingBase):
    __tablename__ = "scrape_runs"
    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(Text)
    tier: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    stage_counts: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    git_sha: Mapped[str | None] = mapped_column(Text)


class RunSourceStatus(StagingBase):
    __tablename__ = "run_source_status"
    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    terminal_status: Mapped[str] = mapped_column(String(20))
    failure: Mapped[str | None] = mapped_column(String(30))
    stage: Mapped[str | None] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PageSnapshot(StagingBase):
    __tablename__ = "page_snapshots"
    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, index=True)
    source_id: Mapped[str] = mapped_column(Text, index=True)
    capture_method: Mapped[str] = mapped_column(String(12))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list[str]] = mapped_column(J, default=list)
    content_type: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    raw_path: Mapped[str] = mapped_column(Text)
    text_path: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(30))
    page_type: Mapped[str | None] = mapped_column(String(40))
    classifier_signals: Mapped[list[str]] = mapped_column(J, default=list)
    capture_conditions: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    supporting_responses: Mapped[list[dict[str, Any]]] = mapped_column(J, default=list)


class PageCheck(StagingBase):
    __tablename__ = "page_checks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text, index=True)
    source_id: Mapped[str] = mapped_column(Text, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(30))
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(12))  # unchanged | changed | reparsed | failed | first


class PageMention(StagingBase):
    __tablename__ = "page_mentions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    snapshot_id: Mapped[str] = mapped_column(Text, index=True)
    canonical_key: Mapped[str] = mapped_column(Text, index=True)
    mention_text: Mapped[str] = mapped_column(Text)


class ExtractionCandidate(StagingBase):
    __tablename__ = "extraction_candidates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(Text, index=True)
    source_id: Mapped[str] = mapped_column(Text, index=True)
    bank_id: Mapped[str] = mapped_column(String(64))
    product_type: Mapped[str] = mapped_column(String(20))
    canonical_key: Mapped[str | None] = mapped_column(Text, index=True)
    parser_name: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(J)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String(14))  # valid | needs_review | reject
    missing_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    parser_notes: Mapped[list[str]] = mapped_column(J, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FieldProvenanceStaging(StagingBase):
    __tablename__ = "field_provenance"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_candidates.id", ondelete="CASCADE"), index=True
    )
    field_path: Mapped[str] = mapped_column(Text)
    value: Mapped[Any] = mapped_column(J, nullable=True)
    null_reason: Mapped[str | None] = mapped_column(String(20))
    snapshot_id: Mapped[str | None] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    span_text: Mapped[str | None] = mapped_column(Text)
    parser_name: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    provenance_class: Mapped[str] = mapped_column(String(24))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Numeric(5, 4))


class ValidationResult(StagingBase):
    __tablename__ = "validation_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_candidates.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    outcome: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(J, default=dict)


class StagedProduct(StagingBase):
    __tablename__ = "staged_products"
    canonical_key: Mapped[str] = mapped_column(Text, primary_key=True)
    bank_id: Mapped[str] = mapped_column(String(64))
    product_type: Mapped[str] = mapped_column(String(20))
    official_name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(String(16))
    last_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DuplicateCandidate(StagingBase):
    __tablename__ = "duplicate_candidates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))  # product | offer
    a: Mapped[str] = mapped_column(Text)
    b: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    similarity: Mapped[float] = mapped_column(Numeric(5, 4))
    proposed_canonical: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(8))  # auto | manual
    final_result: Mapped[str] = mapped_column(Text)


class ManualReviewItem(StagingBase):
    __tablename__ = "manual_review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_kind: Mapped[str] = mapped_column(
        String(20)
    )  # product | offer | duplicate | regulator_conflict | ...
    reason_code: Mapped[str] = mapped_column(String(30))
    bank_id: Mapped[str | None] = mapped_column(String(64))
    product_type: Mapped[str | None] = mapped_column(String(20))
    canonical_key: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    context: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    state: Mapped[str] = mapped_column(
        String(12), default="open"
    )  # open | approved | rejected | merged | edited | superseded
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(Text)


class ReviewDecision(StagingBase):
    __tablename__ = "review_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    queue_id: Mapped[int] = mapped_column(ForeignKey("manual_review_queue.id"))
    action: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(J, default=dict)


class ChangeEvent(StagingBase):
    __tablename__ = "change_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text, index=True)
    canonical_key: Mapped[str] = mapped_column(Text, index=True)
    offer_key: Mapped[str | None] = mapped_column(Text)
    field_path: Mapped[str] = mapped_column(Text)
    old: Mapped[Any] = mapped_column(J, nullable=True)
    new: Mapped[Any] = mapped_column(J, nullable=True)
    change_class: Mapped[str] = mapped_column(String(8))
    rule_id: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CrossCheckResult(StagingBase):
    __tablename__ = "cross_check_results"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text)
    canonical_key: Mapped[str] = mapped_column(Text, index=True)
    dataset: Mapped[str] = mapped_column(Text)
    release_id: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    field_path: Mapped[str] = mapped_column(Text)
    official_value: Mapped[Any] = mapped_column(J, nullable=True)
    regulator_value: Mapped[Any] = mapped_column(J, nullable=True)
    outcome: Mapped[str] = mapped_column(String(12))  # match | explained | conflict | unmatched
    review_id: Mapped[int | None] = mapped_column(Integer)


class RegulatorRelease(StagingBase):
    __tablename__ = "regulator_releases"
    __table_args__ = (UniqueConstraint("dataset", "release_id", name="dataset_release"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    dataset: Mapped[str] = mapped_column(Text)
    release_id: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    file_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RegulatorRecord(StagingBase):
    __tablename__ = "regulator_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    release_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("regulator_releases.id", ondelete="CASCADE"))
    issuer_name: Mapped[str] = mapped_column(Text)
    plan_name: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(J)
    row_ref: Mapped[str] = mapped_column(Text)
    matched_key: Mapped[str | None] = mapped_column(Text)
    match_method: Mapped[str | None] = mapped_column(String(12))


class ProviderRecord(StagingBase):
    __tablename__ = "provider_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_id: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(J)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevalidationOutbox(StagingBase):
    __tablename__ = "revalidation_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Alert(StagingBase):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(Text, index=True)
    state: Mapped[str] = mapped_column(String(10))  # open | resolved
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    webhook_open_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_resolved_sent: Mapped[bool] = mapped_column(Boolean, default=False)
