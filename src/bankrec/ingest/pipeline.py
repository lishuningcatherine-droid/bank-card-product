"""The ingestion pipeline (brief §6.3). Every enabled source ends a run with a terminal status."""

from __future__ import annotations

import logging
import subprocess
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bankrec.alerts import open_regression, resolve
from bankrec.candidate import ProductCandidate
from bankrec.classify.classifier import Classification, classify, classify_pdf, classify_retrieval
from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.dedup.canonical import canonical_key, norm_name, offer_key
from bankrec.dedup.fuzzy import KeyInfo, find_fuzzy
from bankrec.failures import NEXT_ACTION, Failure
from bankrec.freshness import is_stale
from bankrec.ingest.adapters import get_adapter
from bankrec.ingest.adapters.base import ClassifiedPage
from bankrec.ingest.common.html import parse_html
from bankrec.ingest.common.pdf import pdf_to_text
from bankrec.ingest.fetch import FetchResult
from bankrec.ingest.snapshot import store
from bankrec.model import EXTRACTABLE_PAGE_TYPES
from bankrec.publish.changes import diff_offers, diff_product, jsonable
from bankrec.publish.merge import MergedOffer, Meta, merge, meta_priority
from bankrec.publish.publisher import (
    enqueue_revalidation,
    product_tags,
    publish_offer,
    publish_product,
    retire_offer,
    upsert_bank,
    upsert_categories,
)
from bankrec.registry.loader import Registry
from bankrec.registry.schema import SourceEntry
from bankrec.settings import Settings
from bankrec.validation.rules import Verdict, policy, validate

log = logging.getLogger("bankrec.pipeline")

TERMINAL = {
    "published",
    "unchanged",
    "needs_review",
    "rejected_page",
    "rejected_record",
    "retrieval_failed",
    "parser_error",
    "disabled",
    "confirmed",
}


@dataclass
class SourceOutcome:
    source: SourceEntry
    terminal: str = ""
    failure: Failure | None = None
    stage: str = ""
    detail: str = ""
    retrieved_at: datetime | None = None
    page_type: str | None = None
    signals: list[str] = field(default_factory=list)
    retry_status: str = "will retry next scheduled run"
    capture_method: str = "automated"
    candidates: list[tuple[ProductCandidate, Meta, Verdict, uuid.UUID]] = field(default_factory=list)
    regression: str | None = None

    @property
    def next_action(self) -> str:
        return NEXT_ACTION.get(self.failure, "") if self.failure else ""


@dataclass
class ProductOutcome:
    canonical_key: str
    bank_id: str
    product_type: str
    name: str
    decision: str  # published_new | published_version | confirmed | review | rejected
    status: str
    detail: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    offers: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunResult:
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    sources: list[SourceOutcome] = field(default_factory=list)
    products: list[ProductOutcome] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    review_items: list[int] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    registry_gaps: list[str] = field(default_factory=list)


def new_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def _git_sha() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


def rehydrate(c: ProductCandidate) -> ProductCandidate:
    """Restore Decimal/date values after a JSON round-trip through staging."""
    for k, s in list(c.fields.items()):
        v = s.value
        if v is None:
            continue
        if isinstance(v, str) and (k.endswith("_pct") or k == "base_rate"):
            c.fields[k] = s.model_copy(update={"value": Decimal(v)})
        elif isinstance(v, str) and k.endswith("_date"):
            c.fields[k] = s.model_copy(update={"value": date.fromisoformat(v)})
    return c


class Pipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        registry: Registry,
        *,
        fetcher: Any,
        renderer: Any | None = None,
        now: Callable[[], datetime] | None = None,
        trigger: str = "manual",
        tier: str | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self.s, self.settings, self.reg = session, settings, registry
        self.fetcher, self.renderer = fetcher, renderer
        self.now = now or (lambda: datetime.now(UTC))
        self.trigger, self.tier = trigger, tier
        started = self.now()
        self.result = RunResult(new_run_id(started), started)
        self.repo_root = repo_root

    # ------------------------------------------------------------------------------------------------ entry points
    def run(
        self,
        sources: list[SourceEntry] | None = None,
        manual: list[tuple[SourceEntry, FetchResult]] | None = None,
    ) -> RunResult:
        sources = sources if sources is not None else self.reg.enabled(tier=self.tier)
        run = S.ScrapeRun(
            run_id=self.result.run_id,
            started_at=self.result.started_at,
            trigger=self.trigger,
            tier=self.tier,
            status="running",
            git_sha=_git_sha(),
        )
        self.s.add(run)
        for b in self.reg.banks.values():
            if b.role == "bank":
                upsert_bank(self.s, b)
        upsert_categories(self.s)
        self._mirror_registry()
        self.s.flush()
        self.result.registry_gaps = list(self.reg.banks_without_sources)
        for src in sources:
            bank = self.reg.bank(src.bank_id)
            if src.requires_render and self.renderer is not None and not src.fixture_path:
                fr = self.renderer.render(src, bank)
            else:
                fr = self.fetcher.fetch(src, bank)
            self._process(src, fr)
        for src, fr in manual or []:
            self._process(src, fr)
        self._resolve_and_publish()
        self._assert_terminal(sources + [m[0] for m in manual or []])
        self.result.finished_at = self.now()
        run.finished_at, run.status = self.result.finished_at, "completed"
        run.stage_counts = self.counts()
        self.s.flush()
        return self.result

    def counts(self) -> dict[str, Any]:
        c: dict[str, int] = defaultdict(int)
        for o in self.result.sources:
            c[o.terminal] += 1
        return {"sources": dict(c), "products": len(self.result.products)}

    def _mirror_registry(self) -> None:
        for src in self.reg.sources:
            row = self.s.get(S.SourceRegistry, src.source_id) or S.SourceRegistry(source_id=src.source_id)
            row.bank_id, row.product_type = src.bank_id, src.product_type.value if src.product_type else None
            row.source_url, row.source_kind, row.parser_name = (
                str(src.source_url),
                src.source_kind.value,
                src.parser_name,
            )
            row.requires_render, row.enabled, row.priority = src.requires_render, src.enabled, src.priority
            row.expected_entity, row.refresh_tier, row.state = src.expected_entity, src.tier, src.state
            row.test_only, row.notes = self.reg.bank(src.bank_id).test_only, src.notes
            row.config = src.model_dump(mode="json")
            self.s.merge(row)

    def _assert_terminal(self, sources: list[SourceEntry]) -> None:
        seen = {o.source.source_id for o in self.result.sources if o.terminal in TERMINAL}
        missing = [s.source_id for s in sources if s.source_id not in seen]
        if missing:
            raise RuntimeError(f"sources without a terminal status: {missing}")

    # ------------------------------------------------------------------------------------------------ per source
    def _finish(
        self,
        out: SourceOutcome,
        terminal: str,
        failure: Failure | None = None,
        stage: str = "",
        detail: str = "",
    ) -> None:
        out.terminal, out.failure, out.stage, out.detail = terminal, failure, stage, detail
        self.result.sources.append(out)
        self.s.merge(
            S.RunSourceStatus(
                run_id=self.result.run_id,
                source_id=out.source.source_id,
                terminal_status=terminal,
                failure=failure.value if failure else None,
                stage=stage,
                detail=detail[:2000],
                at=self.now(),
            )
        )

    def _page_state(self, src: SourceEntry, url: str) -> S.SourcePage:
        sp = self.s.get(S.SourcePage, src.source_id)
        if sp is None:
            sp = S.SourcePage(
                source_id=src.source_id,
                canonical_url=url,
                consecutive_failures=0,
                health="new",
                last_found_fields=[],
                last_offer_keys=[],
            )
            self.s.add(sp)
        return sp

    def _check(
        self,
        src: SourceEntry,
        fr: FetchResult,
        result: str,
        raw: str | None = None,
        content: str | None = None,
        parser_version: str | None = None,
    ) -> None:
        self.s.add(
            S.PageCheck(
                run_id=self.result.run_id,
                source_id=src.source_id,
                checked_at=fr.retrieved_at,
                outcome=fr.failure.value if fr.failure else "ok",
                raw_sha256=raw,
                content_sha256=content,
                parser_version=parser_version,
                result=result,
            )
        )

    def _process(self, src: SourceEntry, fr: FetchResult) -> None:
        bank = self.reg.bank(src.bank_id)
        out = SourceOutcome(src, retrieved_at=fr.retrieved_at, capture_method=fr.capture_method)
        sp = self._page_state(src, fr.url)
        sp.last_checked_at = fr.retrieved_at
        parser_version = (
            getattr(get_adapter(src.parser_name), "parser_version", None)
            if src.source_kind.value != "regulator_dataset"
            else None
        )
        if fr.failure is not None:
            sp.consecutive_failures += 1
            sp.health = "failing" if sp.consecutive_failures >= 3 else "degraded"
            self._check(src, fr, "failed")
            retry = (
                "manual capture needed"
                if fr.failure in {Failure.ROBOTS_DISALLOWED, Failure.BOT_CHALLENGE, Failure.HTTP_BLOCKED}
                else out.retry_status
            )
            out.retry_status = retry
            return self._finish(out, "retrieval_failed", fr.failure, "retrieve", fr.detail)

        is_pdf = "pdf" in fr.content_type or fr.body[:5] == b"%PDF-"
        doc = None
        try:
            text = pdf_to_text(fr.body) if is_pdf else ""
            if not is_pdf:
                doc = parse_html(fr.body.decode("utf-8", errors="replace"))
                text = doc.text
        except Exception as e:
            self._check(src, fr, "failed")
            return self._finish(out, "parser_error", Failure.PARSE_ERROR, "parse", str(e)[:300])
        snap = store(
            self.settings.data_dir,
            self.result.run_id,
            fr.body,
            text,
            "pdf" if is_pdf else "html",
            supporting=fr.supporting_responses,
        )
        pre = (
            None
            if is_pdf
            else classify_retrieval(
                fr.status, fr.final_url, fr.content_type, doc, bank.official_domains, bank.boilerplate_phrases
            )
        )
        snap_row = S.PageSnapshot(
            snapshot_id=snap.snapshot_id,
            run_id=self.result.run_id,
            source_id=src.source_id,
            capture_method=fr.capture_method if fr.capture_method != "fixture" else "fixture",
            retrieved_at=fr.retrieved_at,
            http_status=fr.status,
            redirect_chain=fr.redirect_chain,
            content_type=fr.content_type,
            raw_sha256=snap.raw_sha256,
            content_sha256=snap.content_sha256,
            raw_path=str(snap.raw_path),
            text_path=str(snap.text_path),
            outcome=pre.failure.value if pre and pre.failure else "ok",
            capture_conditions=fr.capture_conditions,
            supporting_responses=[{"url": r["url"], "status": r["status"]} for r in fr.supporting_responses],
        )
        self.s.merge(snap_row)
        if pre is not None and pre.failure is not None:
            snap_row.page_type, snap_row.classifier_signals = pre.page_type.value, pre.signals
            out.page_type, out.signals = pre.page_type.value, pre.signals
            sp.consecutive_failures += 1
            sp.health = "degraded"
            self._check(src, fr, "failed", snap.raw_sha256, snap.content_sha256)
            out.retry_status = "manual capture needed"
            return self._finish(
                out, "retrieval_failed", pre.failure, "outcome", pre.detail or ",".join(pre.signals)
            )

        # ---- change detection
        unchanged = (
            sp.last_content_sha256 == snap.content_sha256
            and sp.last_parser_version == parser_version
            and sp.health == "healthy"
        )
        if unchanged:
            self._check(src, fr, "unchanged", snap.raw_sha256, snap.content_sha256, parser_version)
            self._confirm_source(src.source_id, fr.retrieved_at)
            sp.consecutive_failures = 0
            return self._finish(out, "unchanged", stage="change_detection", detail="content hash unchanged")
        result_kind = (
            "reparsed"
            if sp.last_content_sha256 == snap.content_sha256
            else "first"
            if sp.last_content_sha256 is None
            else "changed"
        )
        self._check(src, fr, result_kind, snap.raw_sha256, snap.content_sha256, parser_version)

        # ---- classify
        cl: Classification
        if is_pdf:
            cl = classify_pdf(text)
        else:
            assert doc is not None
            cl = classify(
                fr.final_url,
                doc,
                src.expected_entity,
                source_kind=src.source_kind.value,
                boilerplate=bank.boilerplate_phrases,
            )
        snap_row.page_type, snap_row.classifier_signals = cl.page_type.value, cl.signals
        out.page_type, out.signals = cl.page_type.value, cl.signals
        if cl.page_type not in EXTRACTABLE_PAGE_TYPES:
            self._regression(src, sp, bank.bank_id, fr.url, "non_product_page", parser_version, out)
            sp.last_content_sha256, sp.last_parser_version = snap.content_sha256, parser_version
            return self._finish(
                out,
                "rejected_page",
                cl.failure or Failure.NON_PRODUCT_PAGE,
                "classify",
                cl.detail or f"page type {cl.page_type.value}",
            )

        # ---- extract
        page = ClassifiedPage(
            source=src,
            bank=bank,
            url=fr.final_url,
            page_type=cl.page_type,
            retrieved_at=fr.retrieved_at,
            text=text,
            doc=doc,
            snapshot_id=snap.snapshot_id,
            capture_method="manual" if fr.capture_method == "manual" else "automated",
            capture_conditions=fr.capture_conditions,
        )
        try:
            cands = get_adapter(src.parser_name).extract(page)
        except Exception as e:
            log.exception("adapter error", extra={"source_id": src.source_id})
            self._regression(src, sp, bank.bank_id, fr.url, "parser_exception", parser_version, out)
            return self._finish(out, "parser_error", Failure.PARSE_ERROR, "extract", type(e).__name__)
        if not cands:
            self._regression(src, sp, bank.bank_id, fr.url, "no_candidates", parser_version, out)
            return self._finish(
                out, "parser_error", Failure.SCHEMA_DRIFT, "extract", "adapter returned nothing"
            )

        capture_ok = bool(
            fr.capture_conditions.get("capture_context") == "public_default"
            and fr.capture_conditions.get("login") is False
            and not fr.capture_conditions.get("capture_anomaly")
        )
        found_now: set[str] = set()
        for c in cands:
            c.snapshot_id = snap.snapshot_id
            fresh = not is_stale(fr.retrieved_at, "terms", self.now())
            v = validate(c, text, bank.official_domains, fresh=fresh, capture_ok=capture_ok)
            seg = c.value("segment")
            key = (
                canonical_key(
                    c.bank_id, c.product_type.value, seg, c.name or "", c.value("variant"), bank.display_name
                )
                if c.name
                else None
            )
            row = S.ExtractionCandidate(
                run_id=self.result.run_id,
                snapshot_id=snap.snapshot_id,
                source_id=src.source_id,
                bank_id=c.bank_id,
                product_type=c.product_type.value,
                canonical_key=key,
                parser_name=c.parser_name,
                parser_version=c.parser_version,
                payload=c.model_dump(mode="json"),
                confidence=v.confidence,
                status=v.status,
                missing_fields=c.missing_fields,
                parser_notes=c.notes + [f"refused {n}: {t}" for n, t in c.refused_fields],
                created_at=self.now(),
            )
            self.s.add(row)
            self.s.flush()
            for name, sf in c.fields.items():
                self.s.add(
                    S.FieldProvenanceStaging(
                        candidate_id=row.id,
                        field_path=name,
                        value=jsonable(sf.value),
                        null_reason=sf.null_reason.value if sf.null_reason else None,
                        snapshot_id=snap.snapshot_id,
                        span_start=sf.span_start,
                        span_end=sf.span_end,
                        span_text=sf.span_text,
                        parser_name=c.parser_name,
                        parser_version=c.parser_version,
                        provenance_class=sf.provenance_class.value,
                        retrieved_at=fr.retrieved_at,
                        confidence=sf.confidence,
                    )
                )
                if sf.present:
                    found_now.add(name)
            for r in v.results:
                self.s.add(
                    S.ValidationResult(
                        candidate_id=row.id,
                        rule_id=r.rule_id,
                        severity=r.severity,
                        outcome="pass" if r.ok else "fail",
                        message=r.message,
                        details=jsonable(r.details),
                    )
                )
            if key:
                self.s.add(
                    S.PageMention(snapshot_id=snap.snapshot_id, canonical_key=key, mention_text=c.name or "")
                )
            meta = Meta(
                src.source_id,
                snap.snapshot_id,
                fr.final_url,
                c.parser_name,
                c.parser_version,
                fr.retrieved_at,
                meta_priority(cl.page_type),
                fr.capture_conditions,
            )
            out.candidates.append((c, meta, v, row.id))

        # ---- regression (c): a required/key field found last time is missing now
        pol = policy()
        tracked = set()
        for c, *_ in out.candidates:
            tracked |= set(pol["required"][c.product_type.value]) | set(pol["key"][c.product_type.value])
        lost = sorted((set(sp.last_found_fields or []) & tracked) - found_now)
        if lost and sp.health == "healthy":
            self._regression(
                src, sp, bank.bank_id, fr.url, f"fields_lost:{','.join(lost)}", parser_version, out
            )
        else:
            sp.health = "healthy"
            sp.consecutive_failures = 0
            sp.last_successful_parse_at = fr.retrieved_at
            resolve(self.s, self.settings, src.source_id, self.now())
        sp.last_found_fields = sorted(found_now)
        sp.last_content_sha256, sp.last_parser_version = snap.content_sha256, parser_version
        sp.last_snapshot_id, sp.last_changed_at = snap.snapshot_id, fr.retrieved_at
        statuses = {v.status for _, _, v, _ in out.candidates}
        terminal = (
            "rejected_record"
            if statuses == {"reject"}
            else "needs_review"
            if "valid" not in statuses
            else "published"
        )
        self._finish(
            out,
            terminal,
            Failure.VALIDATION_FAILED if terminal == "rejected_record" else None,
            "validate",
            "; ".join(f"{r.rule_id}: {r.message}" for _, _, v, _ in out.candidates for r in v.failed)[:2000],
        )

    def _regression(
        self,
        src: SourceEntry,
        sp: S.SourcePage,
        bank_id: str,
        url: str,
        kind: str,
        parser_version: str | None,
        out: SourceOutcome,
    ) -> None:
        if sp.last_successful_parse_at is None:
            sp.health = "degraded"
            return
        sp.health = "failing"
        sp.consecutive_failures += 1
        out.regression = kind
        alert = open_regression(
            self.s,
            self.settings,
            source_id=src.source_id,
            bank_id=bank_id,
            url=url,
            kind=kind,
            parser_version=parser_version,
            run_id=self.result.run_id,
            now=self.now(),
            last_good=sp.last_successful_parse_at,
        )
        self.result.alerts.append(
            {
                "source_id": src.source_id,
                "bank_id": bank_id,
                "url": url,
                "kind": kind,
                "new_incident": alert is not None,
            }
        )

    def _confirm_source(self, source_id: str, at: datetime) -> None:
        """Unchanged page: advance confirmation for records backed by this source (not recheck-pending ones)."""
        rows = list(self.s.scalars(select(P.FieldProvenance).where(P.FieldProvenance.source_id == source_id)))
        pids = {r.product_id for r in rows}
        for pid in pids:
            p = self.s.get(P.Product, pid)
            if p is None:
                continue
            p.last_checked_at = at
            if p.recheck_pending:
                continue
            for r in rows:
                if r.product_id == pid:
                    r.last_confirmed_at = at
            confirmed = self.s.scalar(
                select(func.min(P.FieldProvenance.last_confirmed_at)).where(
                    P.FieldProvenance.product_id == pid,
                    P.FieldProvenance.offer_id.is_(None),
                    P.FieldProvenance.null_reason.is_(None),
                )
            )
            p.last_confirmed_at = confirmed or at
            if p.product_type == "savings":
                p.apy_confirmed_at = at
            for o in p.offers:
                if o.status == "current" and any(r.offer_id == o.id for r in rows):
                    o.last_confirmed_at = at
            enqueue_revalidation(self.s, product_tags(p), at)

    # ------------------------------------------------------------------------------------------------ resolve/publish
    def _review(
        self,
        kind: str,
        reason: str,
        *,
        bank_id: str | None,
        product_type: str | None,
        key: str | None,
        candidate_id: uuid.UUID | None,
        context: dict[str, Any],
    ) -> int:
        open_same = self.s.scalar(
            select(S.ManualReviewItem).where(
                S.ManualReviewItem.state == "open",
                S.ManualReviewItem.item_kind == kind,
                S.ManualReviewItem.reason_code == reason,
                S.ManualReviewItem.canonical_key == key,
            )
        )
        if open_same is not None:
            open_same.context, open_same.candidate_id, open_same.run_id = (
                jsonable(context),
                candidate_id,
                self.result.run_id,
            )
            self.result.review_items.append(open_same.id)
            return open_same.id
        item = S.ManualReviewItem(
            item_kind=kind,
            reason_code=reason,
            bank_id=bank_id,
            product_type=product_type,
            canonical_key=key,
            candidate_id=candidate_id,
            context=jsonable(context),
            created_at=self.now(),
            run_id=self.result.run_id,
        )
        self.s.add(item)
        self.s.flush()
        self.result.review_items.append(item.id)
        return item.id

    def _resolve_and_publish(self) -> None:
        groups: dict[str, list[tuple[ProductCandidate, Meta, Verdict, uuid.UUID]]] = defaultdict(list)
        for o in self.result.sources:
            for c, meta, v, cid in o.candidates:
                if v.status == "reject" or not c.name:
                    self.result.products.append(
                        ProductOutcome(
                            "",
                            c.bank_id,
                            c.product_type.value,
                            c.name or "(no name)",
                            "rejected",
                            v.status,
                            "; ".join(f"{r.rule_id}: {r.message}" for r in v.failed),
                        )
                    )
                    continue
                key = canonical_key(
                    c.bank_id,
                    c.product_type.value,
                    c.value("segment"),
                    c.name,
                    c.value("variant"),
                    self.reg.bank(c.bank_id).display_name,
                )
                groups[key].append((c, meta, v, cid))
        now = self.now()
        for key, items in groups.items():
            self._publish_group(key, items, now)
        self._fuzzy(list(groups))

    def _publish_group(
        self, key: str, items: list[tuple[ProductCandidate, Meta, Verdict, uuid.UUID]], now: datetime
    ) -> None:
        mp = merge([(c, m) for c, m, _, _ in items], key)
        if len(items) > 1:  # exact canonical-key match across sources: automatic merge (brief §8)
            srcs = sorted({m.source_id for _, m, _, _ in items})
            for other in srcs[1:]:
                self.s.add(
                    S.DuplicateCandidate(
                        run_id=self.result.run_id,
                        kind="product",
                        a=srcs[0],
                        b=other,
                        reason="exact canonical key",
                        similarity=1,
                        proposed_canonical=key,
                        decision="auto",
                        final_result=f"merged into {key}",
                    )
                )
                self.result.duplicates.append(
                    {
                        "a": srcs[0],
                        "b": other,
                        "reason": "exact canonical key",
                        "proposed": key,
                        "confidence": 1.0,
                        "decision": "auto",
                        "result": f"merged into {key}",
                    }
                )
        bank = self.reg.bank(mp.bank_id)
        verdicts = [v for _, _, v, _ in items]
        cids = [str(cid) for *_, cid in items]
        # offers: validated independently of the product
        for c, meta, v, _ in items:
            for ov in v.offers:
                so = c.offers[ov.index]
                assert so.value is not None
                mp.offers.append(MergedOffer(so.value, so, meta, ov.status))
        status = (
            "valid" if all(v.status == "valid" for v in verdicts) and not mp.conflicts else "needs_review"
        )
        missing_key = sorted({f for v in verdicts for f in v.missing_key})
        missing_all = sorted(set(items[0][0].missing_fields))
        po = ProductOutcome(key, mp.bank_id, mp.product_type, mp.name, "", status, missing=missing_key)
        self.result.products.append(po)
        existing = self.s.scalar(select(P.Product).where(P.Product.canonical_key == key))
        ctx_base = {
            "candidate_ids": cids,
            "name": mp.name,
            "url": mp.primary_meta.url,
            "failed_rules": [
                {"rule": r.rule_id, "message": r.message, "details": r.details}
                for v in verdicts
                for r in v.failed
            ],
            "conflicts": mp.conflicts,
            "missing_key": missing_key,
        }
        if status != "valid":
            rid = self._review(
                "product",
                "conflict" if mp.conflicts else "needs_review",
                bank_id=mp.bank_id,
                product_type=mp.product_type,
                key=key,
                candidate_id=uuid.UUID(cids[0]),
                context=ctx_base,
            )
            po.decision, po.detail = "review", f"review item {rid}"
            if existing is not None and not existing.recheck_pending:
                existing.recheck_pending, existing.recheck_reason = True, "needs_review"
                enqueue_revalidation(self.s, product_tags(existing), now)
            return

        valid_offers = [o for o in mp.offers if o.status == "valid"]
        for o in mp.offers:
            po.offers.append(
                {
                    "type": o.rec.offer_type,
                    "qualifier": o.rec.amount_qualifier,
                    "amount_min": o.rec.amount_min,
                    "amount_max": o.rec.amount_max,
                    "status": o.status,
                }
            )
            if o.status == "needs_review":
                self._review(
                    "offer",
                    "offer_needs_review",
                    bank_id=mp.bank_id,
                    product_type=mp.product_type,
                    key=key,
                    candidate_id=uuid.UUID(cids[0]),
                    context={**ctx_base, "offer": jsonable(o.rec)},
                )

        if existing is None:
            product = publish_product(
                self.s,
                mp,
                bank,
                run_id=self.result.run_id,
                now=now,
                missing_fields=missing_all,
                critical_missing=missing_key,
                changes=None,
                existing=None,
            )
            for o in valid_offers:
                publish_offer(self.s, product, o, run_id=self.result.run_id, now=now)
            po.decision = "published_new"
            return

        old_snap = self.s.scalar(
            select(P.ProductVersion.snapshot).where(
                P.ProductVersion.product_id == existing.id, P.ProductVersion.valid_to.is_(None)
            )
        )
        changes = diff_product(old_snap or {}, mp.snapshot())
        old_offers = {
            o.offer_key: {"offer_type": o.offer_type, "id": str(o.id)}
            for o in existing.offers
            if o.status in {"current", "recheck_pending"}
        }
        new_offers: dict[str, MergedOffer] = {
            offer_key(key, jsonable(o.rec.model_dump())): o for o in valid_offers
        }
        offer_changes = diff_offers(
            old_offers,
            {k: {"offer_type": o.rec.offer_type} for k, o in new_offers.items()},
            product_is_new=False,
        )
        all_changes = changes + offer_changes
        po.changes = [{"field": ch.field, "class": ch.change_class, "rule": ch.rule} for ch in all_changes]
        for ch in all_changes:
            self.s.add(
                S.ChangeEvent(
                    run_id=self.result.run_id,
                    canonical_key=key,
                    field_path=ch.field,
                    old=jsonable(ch.old) if not isinstance(ch.old, dict) or "o" not in ch.old else None,
                    new=None if isinstance(ch.new, dict) else jsonable(ch.new),
                    change_class=ch.change_class,
                    rule_id=ch.rule,
                    decision="queued" if ch.change_class == "major" else "auto_published",
                    at=now,
                )
            )
        if any(ch.change_class == "major" for ch in all_changes):
            existing.recheck_pending, existing.recheck_reason = True, "major_change"
            existing.recheck_fields = sorted({ch.field for ch in all_changes if ch.change_class == "major"})
            existing.last_checked_at = now
            for oc in offer_changes:
                if oc.rule in {"offer_disappeared", "offer_changed"} and oc.old:
                    for eo in existing.offers:
                        if str(eo.id) == oc.old.get("id") and eo.status == "current":
                            eo.status, eo.recheck_reason = "recheck_pending", oc.rule
            rid = self._review(
                "product",
                "major_change",
                bank_id=mp.bank_id,
                product_type=mp.product_type,
                key=key,
                candidate_id=uuid.UUID(cids[0]),
                context={
                    **ctx_base,
                    "changes": [
                        {
                            "field": ch.field,
                            "old": jsonable(ch.old),
                            "new": jsonable(ch.new) if not isinstance(ch.new, dict) else "offer",
                            "rule": ch.rule,
                        }
                        for ch in all_changes
                        if ch.change_class == "major"
                    ],
                },
            )
            enqueue_revalidation(self.s, product_tags(existing), now)
            po.decision, po.detail = "review", f"major change → review item {rid}; old value stays live"
            return
        if changes:
            publish_product(
                self.s,
                mp,
                bank,
                run_id=self.result.run_id,
                now=now,
                missing_fields=missing_all,
                critical_missing=missing_key,
                changes=changes,
                existing=existing,
            )
            po.decision = "published_version"
        else:
            existing.last_confirmed_at = existing.last_checked_at = existing.verified_at = now
            if existing.product_type == "savings":
                existing.apy_confirmed_at = now
            existing.missing_fields, existing.critical_missing = missing_all, missing_key
            existing.recheck_pending, existing.recheck_reason, existing.recheck_fields = False, None, []
            for r in self.s.scalars(
                select(P.FieldProvenance).where(P.FieldProvenance.product_id == existing.id)
            ):
                r.last_confirmed_at = now
            enqueue_revalidation(self.s, product_tags(existing), now)
            po.decision = "confirmed"
        for entry in new_offers.values():
            publish_offer(self.s, existing, entry, run_id=self.result.run_id, now=now)

    def _fuzzy(self, keys: list[str]) -> None:
        infos: list[KeyInfo] = []
        for p in self.s.scalars(select(P.Product)):
            fee = p.card.annual_fee_cents if p.card else None
            infos.append(
                KeyInfo(
                    p.canonical_key,
                    p.bank_id,
                    p.product_type,
                    norm_name(
                        p.official_name,
                        self.reg.banks[p.bank_id].display_name if p.bank_id in self.reg.banks else None,
                    ),
                    p.card.segment if p.card else "personal",
                    fee,
                    p.card.co_brand_partner if p.card else None,
                )
            )
        known = {i.key for i in infos}
        for k in keys:
            if k not in known:
                bank_id, ptype, seg, name, _ = k.split(":", 4)
                infos.append(KeyInfo(k, bank_id, ptype, name, seg))
        for d in find_fuzzy(infos):
            self.s.add(
                S.DuplicateCandidate(
                    run_id=self.result.run_id,
                    kind="product",
                    a=d.a,
                    b=d.b,
                    reason=d.reason,
                    similarity=d.similarity,
                    proposed_canonical=d.proposed,
                    decision=d.decision,
                    final_result="pending review",
                )
            )
            rid = self._review(
                "duplicate",
                "fuzzy_match",
                bank_id=d.a.split(":")[0],
                product_type=d.a.split(":")[1],
                key=f"{d.a}|{d.b}",
                candidate_id=None,
                context={"a": d.a, "b": d.b, "reason": d.reason, "proposed": d.proposed},
            )
            self.result.duplicates.append(
                {
                    "a": d.a,
                    "b": d.b,
                    "reason": d.reason,
                    "proposed": d.proposed,
                    "confidence": d.similarity,
                    "decision": d.decision,
                    "result": f"review item {rid}",
                }
            )


def retire_missing_offer(session: Session, offer: P.Offer, now: datetime) -> None:
    retire_offer(session, offer, status="recheck_pending", reason="offer_disappeared", now=now)
