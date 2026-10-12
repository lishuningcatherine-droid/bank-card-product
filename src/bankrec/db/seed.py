"""Export/seed published ``prod`` data only (brief §14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from bankrec.db import prod as P
from bankrec.publish.changes import jsonable

ORDER = [P.Bank, P.RewardCategory, P.Product, P.ProductAlias, P.CreditCardDetails, P.CheckingAccountDetails,
         P.SavingsAccountDetails, P.ProductRewardRate, P.ProductBenefit, P.Offer, P.ProductVersion, P.OfferVersion,
         P.FieldProvenance]


def export_prod(session: Session, path: Path) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for model in ORDER:
            cols = model.__table__.columns.keys()
            for row in session.execute(select(model.__table__)).mappings():
                f.write(json.dumps({"table": model.__tablename__, "row": {c: jsonable(row[c]) for c in cols}},
                                   default=str) + "\n")
                n += 1
    return n


def seed_prod(session: Session, path: Path, *, include_test: bool = False) -> dict[str, int]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            rows.setdefault(rec["table"], []).append(rec["row"])
    test_banks = {r["bank_id"] for r in rows.get("banks", []) if r.get("test_only")}
    test_products = {r["id"] for r in rows.get("products", []) if r.get("test_only") or r["bank_id"] in test_banks}
    if (test_banks or test_products) and not include_test:
        raise ValueError(f"seed file contains test_only data ({sorted(test_banks)}); refusing without --include-test")
    stats: dict[str, int] = {}
    for model in ORDER:
        data = rows.get(model.__tablename__, [])
        if data:
            session.execute(insert(model.__table__), data)
        stats[model.__tablename__] = len(data)
    return stats
