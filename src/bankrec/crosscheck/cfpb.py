"""CFPB cross-check (DESIGN §21.7). Regulator data never creates products, offers, or published values."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

import yaml
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.db import staging as S
from bankrec.dedup.canonical import norm_name
from bankrec.failures import Failure
from bankrec.ingest.common.pdf import pdf_to_text
from bankrec.ingest.snapshot import sha256
from bankrec.parsers.money import parse_money
from bankrec.parsers.percent import parse_percent, parse_percent_range
from bankrec.publish.changes import jsonable
from bankrec.registry.loader import Registry
from bankrec.settings import CONFIG_DIR
from bankrec.validation.rules import policy

COMPARED = [
    "purchase_apr_min_pct",
    "purchase_apr_max_pct",
    "annual_fee_cents",
    "foreign_tx_fee_pct",
    "bt_fee_pct",
    "cash_fee_pct",
]


class RegulatorSchemaError(Exception):
    failure = Failure.SCHEMA_DRIFT


@dataclass
class RegulatorRow:
    issuer_name: str
    plan_name: str
    fields: dict[str, Any]
    row_ref: str


@dataclass
class CrossCheckSummary:
    matched: int = 0
    unmatched: int = 0
    conflicts: int = 0
    explained: int = 0
    agreements: int = 0
    review_ids: list[int] = field(default_factory=list)


@lru_cache(maxsize=1)
def tccp_mapping() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "regulators" / "cfpb_tccp.yaml").read_text(encoding="utf-8")))


def _num(v: str) -> Decimal | None:
    v = (v or "").strip().replace("%", "").replace("$", "").replace(",", "")
    if not v or v.lower() in {"n/a", "na", "none", "-"}:
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def parse_tccp(data: bytes) -> list[RegulatorRow]:
    """CSV or the .xlsx CFPB publishes (detected by the ZIP signature)."""
    return parse_tccp_xlsx(data) if data[:2] == b"PK" else parse_tccp_csv(data)


def parse_tccp_xlsx(data: bytes) -> list[RegulatorRow]:
    """The published workbook has title rows above the header; the header is the row naming the issuer column."""
    import openpyxl

    m = tccp_mapping()
    cols: dict[str, str] = m["columns"]
    ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    rows_iter = list(ws.iter_rows(values_only=True))
    hdr_i = next(
        (
            i
            for i, r in enumerate(rows_iter[:50])
            if r and cols["issuer_name"] in [str(c).strip() if c else "" for c in r]
        ),
        None,
    )
    if hdr_i is None:
        raise RegulatorSchemaError(f"TCCP workbook has no header row with {cols['issuer_name']!r}")
    header = [str(c).strip() if c is not None else "" for c in rows_iter[hdr_i]]
    dicts = [
        {h: ("" if v is None else str(v)) for h, v in zip(header, r, strict=False) if h}
        for r in rows_iter[hdr_i + 1 :]
        if r and any(v is not None for v in r)
    ]
    return _rows_from_dicts(dicts, set(header), m, first_row=hdr_i + 2)


def parse_tccp_csv(data: bytes) -> list[RegulatorRow]:
    m = tccp_mapping()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    return _rows_from_dicts(list(reader), set(reader.fieldnames or []), m, first_row=2)


def _rows_from_dicts(
    records: list[dict[str, str]], header: set[str], m: dict[str, Any], first_row: int
) -> list[RegulatorRow]:
    cols: dict[str, str] = m["columns"]
    missing = [c for c in cols.values() if c not in header]
    if missing:
        raise RegulatorSchemaError(
            f"TCCP file lacks mapped columns {missing}; update config/regulators/cfpb_tccp.yaml"
        )
    fractions = set(m.get("fraction_columns", []))
    rows: list[RegulatorRow] = []
    for i, r in enumerate(records, start=first_row):
        if not (r.get(cols["issuer_name"]) or "").strip():
            continue
        f: dict[str, Any] = {}
        for logical, col in cols.items():
            if logical in {"issuer_name", "plan_name"}:
                continue
            n = _num(r.get(col, ""))
            if n is not None and logical in fractions:
                n = (n * 100).quantize(Decimal("0.01"))  # 0.18239999999999998 → 18.24
            if n is not None and logical in m.get("money_columns", []):
                f[logical] = int(n * 100)
            elif n is not None:
                f[logical] = n
        rows.append(
            RegulatorRow(
                r[cols["issuer_name"]].strip(),
                r[cols["plan_name"]].replace("\xa0", " ").strip(),
                f,
                f"row {i}",
            )
        )
    return rows


def parse_agreement_pdf(data: bytes, issuer_name: str, plan_name: str, ref: str) -> RegulatorRow:
    text = pdf_to_text(data)
    f: dict[str, Any] = {}
    for line in text.split("\n"):
        low = line.lower()
        if low.startswith("annual fee"):
            v = parse_money(line)
            if v is not None:
                f["annual_fee_cents"] = v
        elif re.match(r"(apr|annual percentage rate) for purchases|purchase apr", low):
            rng = parse_percent_range(line)
            if rng:
                f["purchase_apr_min_pct"], f["purchase_apr_max_pct"] = rng.low, rng.high
        elif low.startswith("foreign transaction"):
            if re.search(r"\bnone\b", low):
                f["foreign_tx_fee_pct"] = Decimal(0)
            elif (p := parse_percent(line)) is not None:
                f["foreign_tx_fee_pct"] = p
    return RegulatorRow(issuer_name, plan_name, f, ref)


def _official(p: P.Product, k: str) -> Any:
    return getattr(p.card, k, None) if p.card is not None else None


def _equal(a: Any, b: Any) -> bool:
    tol = policy()["sanity"]
    if isinstance(a, int) and isinstance(b, int):
        return abs(a - b) <= tol["regulator_tolerance_cents"]
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal(str(tol["regulator_tolerance_pct"]))
    except InvalidOperation:
        return a == b


def _explained_by_history(session: Session, p: P.Product, k: str, reg_value: Any, as_of: date | None) -> bool:
    if as_of is None:
        return False
    versions = list(
        session.scalars(
            select(P.ProductVersion)
            .where(P.ProductVersion.product_id == p.id)
            .order_by(P.ProductVersion.version)
        )
    )
    for v in versions:
        if v.valid_from.date() <= as_of and (v.valid_to is None or v.valid_to.date() >= as_of):
            old = (v.snapshot.get("fields") or {}).get(k)
            return (
                old is not None
                and _equal(old if not isinstance(old, str) else Decimal(old), reg_value)
                and v.valid_to is not None
            )
    return False


def run_crosscheck(
    session: Session,
    registry: Registry,
    *,
    dataset: str,
    release_id: str,
    as_of: date | None,
    file_url: str,
    data: bytes,
    rows: list[RegulatorRow],
    run_id: str,
    now: datetime,
) -> CrossCheckSummary:
    rel = session.scalar(
        select(S.RegulatorRelease).where(
            S.RegulatorRelease.dataset == dataset, S.RegulatorRelease.release_id == release_id
        )
    )
    if rel is None:
        rel = S.RegulatorRelease(
            dataset=dataset,
            release_id=release_id,
            as_of_date=as_of,
            file_url=file_url,
            sha256=sha256(data),
            retrieved_at=now,
        )
        session.add(rel)
        session.flush()
    issuer_to_bank = {n.lower(): b.bank_id for b in registry.banks.values() for n in b.cfpb_issuer_names}
    summary = CrossCheckSummary()
    downgrade = bool(policy().get("regulator_conflict_downgrades", False))
    for row in rows:
        rec = S.RegulatorRecord(
            release_pk=rel.id,
            issuer_name=row.issuer_name,
            plan_name=row.plan_name,
            fields=jsonable(row.fields),
            row_ref=row.row_ref,
        )
        session.add(rec)
        bank_id = issuer_to_bank.get(row.issuer_name.lower())
        if bank_id is None:
            summary.unmatched += 1
            continue
        bank = registry.bank(bank_id)
        products = list(
            session.scalars(
                select(P.Product).where(P.Product.bank_id == bank_id, P.Product.product_type == "credit_card")
            )
        )
        target = norm_name(row.plan_name, bank.display_name)
        exact = [
            p
            for p in products
            if norm_name(p.official_name, bank.display_name) == target
            or any(norm_name(a.alias, bank.display_name) == target for a in p.aliases)
        ]
        if not exact:
            fuzzy = [
                p
                for p in products
                if fuzz.token_set_ratio(norm_name(p.official_name, bank.display_name), target) >= 85
            ]
            if fuzzy:
                it = S.ManualReviewItem(
                    item_kind="regulator_match",
                    reason_code="fuzzy_regulator_match",
                    bank_id=bank_id,
                    product_type="credit_card",
                    canonical_key=fuzzy[0].canonical_key,
                    context={
                        "dataset": dataset,
                        "release": release_id,
                        "plan": row.plan_name,
                        "candidates": [p.canonical_key for p in fuzzy],
                    },
                    created_at=now,
                    run_id=run_id,
                )
                session.add(it)
                session.flush()
                summary.review_ids.append(it.id)
            summary.unmatched += 1
            session.add(
                S.CrossCheckResult(
                    run_id=run_id,
                    canonical_key=f"{bank_id}:?:{target}",
                    dataset=dataset,
                    release_id=release_id,
                    as_of_date=as_of,
                    field_path="*",
                    official_value=None,
                    regulator_value=None,
                    outcome="unmatched",
                )
            )
            continue
        p = exact[0]
        rec.matched_key, rec.match_method = p.canonical_key, "exact"
        summary.matched += 1
        for k in COMPARED:
            if k not in row.fields:
                continue
            off = _official(p, k)
            if off is None:
                continue
            reg = row.fields[k]
            if _equal(off, reg):
                outcome = "match"
                summary.agreements += 1
            elif _explained_by_history(session, p, k, reg, as_of):
                outcome = "explained"
                summary.explained += 1
            else:
                outcome = "conflict"
                summary.conflicts += 1
            ccr = S.CrossCheckResult(
                run_id=run_id,
                canonical_key=p.canonical_key,
                dataset=dataset,
                release_id=release_id,
                as_of_date=as_of,
                field_path=k,
                official_value=jsonable(off),
                regulator_value=jsonable(reg),
                outcome=outcome,
            )
            if outcome == "conflict":
                it = S.ManualReviewItem(
                    item_kind="regulator_conflict",
                    reason_code="regulator_conflict",
                    bank_id=bank_id,
                    product_type="credit_card",
                    canonical_key=p.canonical_key,
                    context={
                        "field": k,
                        "official": jsonable(off),
                        "official_url": p.official_url,
                        "regulator": jsonable(reg),
                        "dataset": dataset,
                        "release": release_id,
                        "as_of": as_of.isoformat() if as_of else None,
                        "row_ref": row.row_ref,
                    },
                    created_at=now,
                    run_id=run_id,
                )
                session.add(it)
                session.flush()
                ccr.review_id = it.id
                summary.review_ids.append(it.id)
                if downgrade and not p.recheck_pending:
                    p.recheck_pending, p.recheck_reason = True, "regulator_conflict"
            session.add(ccr)
    session.flush()
    return summary
