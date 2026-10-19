"""Run reports: CSV + Markdown per report and a summary.md index (brief §15)."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.freshness import is_stale, offer_state, product_label
from bankrec.ingest.pipeline import RunResult
from bankrec.registry.loader import Registry

FAILURE_COLS = ["bank", "url", "time", "stage", "failure", "detail", "retry_status", "next_action"]


def _write(
    dirpath: Path, name: str, title: str, cols: list[str], rows: list[dict[str, Any]], intro: str = ""
) -> str:
    dirpath.mkdir(parents=True, exist_ok=True)
    with (dirpath / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    md = [f"# {title}", ""]
    if intro:
        md += [intro, ""]
    md.append(f"Rows: {len(rows)}")
    md.append("")
    if rows:
        md.append("| " + " | ".join(cols) + " |")
        md.append("|" + "---|" * len(cols))
        for r in rows:
            md.append(
                "| "
                + " | ".join(str(r.get(c, "")).replace("|", "\\|").replace("\n", " ")[:300] for c in cols)
                + " |"
            )
    (dirpath / f"{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return name


def manual_capture_instructions(bank_id: str, slug: str, url: str) -> str:
    return (
        f"Open {url} in a normal browser; save it with the SingleFile extension (or the PDF) to "
        f"data/manual_snapshots/{bank_id}/{slug}.html; run `bankrec ingest --manual "
        f"data/manual_snapshots/{bank_id}/{slug}.html --source-url {url} --captured-at <YYYY-MM-DD>`"
    )


def write_reports(
    session: Session,
    result: RunResult,
    registry: Registry,
    reports_dir: Path,
    now: datetime,
    reachability: list[dict[str, Any]] | None = None,
) -> Path:
    d = reports_dir / result.run_id
    written: list[tuple[str, str, int]] = []

    def w(name: str, title: str, cols: list[str], rows: list[dict[str, Any]], intro: str = "") -> None:
        _write(d, name, title, cols, rows, intro)
        written.append((name, title, len(rows)))

    src_rows = []
    for o in result.sources:
        src_rows.append(
            {
                "bank": o.source.bank_id,
                "source_id": o.source.source_id,
                "url": str(o.source.source_url),
                "time": o.retrieved_at.isoformat() if o.retrieved_at else "",
                "terminal_status": o.terminal,
                "stage": o.stage,
                "failure": o.failure.value if o.failure else "",
                "detail": o.detail,
                "retry_status": o.retry_status,
                "next_action": o.next_action,
                "page_type": o.page_type or "",
                "signals": ";".join(o.signals),
                "capture_method": o.capture_method,
            }
        )
    w(
        "source_status",
        "Source terminal status (every registry source)",
        ["bank", "source_id", "url", "terminal_status", "failure", "stage", "page_type", "time"],
        src_rows,
    )
    w(
        "retrieval_failures",
        "Retrieval failures",
        FAILURE_COLS,
        [r for r in src_rows if r["terminal_status"] == "retrieval_failed"],
    )
    w(
        "page_classifications",
        "Page classifications",
        ["bank", "url", "page_type", "signals", "time"],
        [r for r in src_rows if r["page_type"]],
    )
    w(
        "parser_errors",
        "Parser errors",
        FAILURE_COLS,
        [r for r in src_rows if r["terminal_status"] == "parser_error"],
    )
    w(
        "parser_regressions",
        "Parser regressions (previously working sources)",
        ["bank_id", "source_id", "url", "kind", "new_incident"],
        result.alerts,
    )
    w(
        "rejected_pages",
        "Rejected pages (non-product or failed)",
        FAILURE_COLS,
        [r for r in src_rows if r["terminal_status"] == "rejected_page"],
    )

    prod_rows = [
        {
            "bank": p.bank_id,
            "type": p.product_type,
            "name": p.name,
            "decision": p.decision,
            "status": p.status,
            "detail": p.detail,
            "missing": ", ".join(p.missing),
            "changes": "; ".join(f"{c['field']}({c['class']})" for c in p.changes),
        }
        for p in result.products
    ]
    w(
        "missing_fields",
        "Missing key fields",
        ["bank", "type", "name", "missing"],
        [r for r in prod_rows if r["missing"]],
    )
    w(
        "rejected_records",
        "Rejected records",
        ["bank", "type", "name", "detail"],
        [r for r in prod_rows if r["decision"] == "rejected"],
    )
    w(
        "changes",
        "Detected changes",
        ["bank", "type", "name", "decision", "changes"],
        [r for r in prod_rows if r["changes"]],
    )

    conflicts, reviews = [], []
    for it in session.scalars(select(S.ManualReviewItem).where(S.ManualReviewItem.state == "open")):
        reviews.append(
            {
                "id": it.id,
                "kind": it.item_kind,
                "reason": it.reason_code,
                "bank": it.bank_id or "",
                "type": it.product_type or "",
                "key": it.canonical_key or "",
                "created_at": it.created_at.isoformat(),
            }
        )
        for cf in (it.context or {}).get("conflicts", []):
            conflicts.append(
                {
                    "key": it.canonical_key,
                    "field": cf["field"],
                    "values": "; ".join(f"{v['value']} ({v['source']})" for v in cf["values"]),
                }
            )
    w("conflicts", "Conflicting values", ["key", "field", "values"], conflicts)
    w(
        "review_items",
        "Open manual-review items",
        ["id", "kind", "reason", "bank", "type", "key", "created_at"],
        reviews,
    )
    w(
        "duplicates",
        "Duplicate candidates",
        ["a", "b", "reason", "proposed", "confidence", "decision", "result"],
        result.duplicates,
    )

    published, stale, recheck, ready, expired = [], [], [], [], []
    counts: Counter[tuple[str, str, str]] = Counter()
    for p in session.scalars(select(P.Product)):
        label, reasons = product_label(
            published=True,
            terms_confirmed_at=p.last_confirmed_at,
            apy_confirmed_at=p.apy_confirmed_at,
            product_type=p.product_type,
            missing_key=p.critical_missing,
            recheck_pending=p.recheck_pending,
            provider_only_fields=p.provider_only_fields,
            now=now,
        )
        row = {
            "bank": p.bank_id,
            "type": p.product_type,
            "name": p.official_name,
            "label": label,
            "reasons": "; ".join(reasons),
            "verified_at": p.verified_at.isoformat(),
            "last_confirmed_at": p.last_confirmed_at.isoformat(),
            "url": p.official_url,
            "recheck_reason": p.recheck_reason or "",
        }
        published.append(row)
        counts[(p.bank_id, p.product_type, label)] += 1
        if is_stale(p.last_confirmed_at, "terms", now) or (
            p.product_type == "savings" and is_stale(p.apy_confirmed_at, "apy", now)
        ):
            stale.append(row)
        if p.recheck_pending:
            recheck.append(row)
        if label == "verified":
            ready.append(row)
        for off in p.offers:
            st = offer_state(off.status, off.expiration_date, off.last_confirmed_at, now)
            if st == "expired":
                expired.append(
                    {
                        "bank": p.bank_id,
                        "name": p.official_name,
                        "offer_type": off.offer_type,
                        "expiration_date": str(off.expiration_date),
                        "url": off.offer_url,
                    }
                )
            if st == "stale":
                stale.append({**row, "reasons": f"offer {off.offer_type} not recently verified"})
            if off.status == "recheck_pending":
                recheck.append({**row, "reasons": f"offer {off.offer_type}: {off.recheck_reason}"})
    cols = ["bank", "type", "name", "label", "reasons", "verified_at", "last_confirmed_at", "url"]
    w("published_records", "Published records", cols, published)
    w("stale_records", "Stale records (due for recheck)", cols, stale)
    w(
        "expired_offers",
        "Expired offers (kept in history, never shown as current)",
        ["bank", "name", "offer_type", "expiration_date", "url"],
        expired,
    )
    w("recheck_pending", "Recheck-pending items", [*cols, "recheck_reason"], recheck)
    w("recommendation_ready", "Recommendation-ready products (Verified)", cols, ready)
    cc = [
        {
            "key": r.canonical_key,
            "dataset": r.dataset,
            "release": r.release_id,
            "field": r.field_path,
            "official": r.official_value,
            "regulator": r.regulator_value,
            "outcome": r.outcome,
            "review_id": r.review_id or "",
        }
        for r in session.scalars(select(S.CrossCheckResult).where(S.CrossCheckResult.run_id == result.run_id))
    ]
    w(
        "cross_check_conflicts",
        "Cross-check results (CFPB)",
        ["key", "dataset", "release", "field", "official", "regulator", "outcome", "review_id"],
        cc,
    )
    count_rows = []
    for b in sorted(b for b, cfg in registry.banks.items() if cfg.role == "bank"):
        for t in ("credit_card", "checking", "savings"):
            avail = registry.banks[b].product_types.get(t)  # type: ignore[call-overload]
            count_rows.append(
                {
                    "bank": b,
                    "type": t,
                    "availability": avail.availability if avail else "unknown",
                    "verified": counts[(b, t, "verified")],
                    "partially_verified": counts[(b, t, "partially_verified")],
                    "sources_enabled": len(
                        [s for s in registry.enabled(bank=b) if s.product_type and s.product_type.value == t]
                    ),
                }
            )
    w(
        "counts",
        "Counts by bank × type × status",
        ["bank", "type", "availability", "sources_enabled", "verified", "partially_verified"],
        count_rows,
    )

    # manual verification needed
    mv = []
    for r in src_rows:
        if r["terminal_status"] in {"retrieval_failed", "rejected_page"}:
            slug = r["source_id"].split(":", 1)[1]
            mv.append(
                {
                    "bank": r["bank"],
                    "url": r["url"],
                    "reason": r["failure"],
                    "instructions": manual_capture_instructions(r["bank"], slug, r["url"]),
                }
            )
    for b in result.registry_gaps:
        mv.append(
            {
                "bank": b,
                "url": f"(no confirmed product URLs in config/sources/{b}.yaml)",
                "reason": "NO_SOURCES",
                "instructions": "Confirm official product-detail URLs (see docs/REACHABILITY.md) and add them "
                "to the registry, or capture pages manually.",
            }
        )
    for row in reachability or []:
        mv.append(row)
    w(
        "manual_verification_needed",
        "Manual verification needed",
        ["bank", "url", "reason", "instructions"],
        mv,
        intro="Sources that could not be retrieved or verified automatically. No data was substituted for them.",
    )

    lines = [
        f"# Run {result.run_id}",
        "",
        f"- Started: {result.started_at.isoformat()}",
        f"- Finished: {result.finished_at.isoformat() if result.finished_at else ''}",
        f"- Sources processed: {len(result.sources)}",
        f"- Terminal statuses: {dict(Counter(o.terminal for o in result.sources))}",
        f"- Products in run: {len(result.products)}",
        f"- Banks with no enabled sources: {', '.join(result.registry_gaps) or 'none'}",
        "",
        "| Report | Rows |",
        "|---|---|",
    ]
    lines += [f"| [{t}]({n}.md) | {c} |" for n, t, c in written]
    (d / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d
