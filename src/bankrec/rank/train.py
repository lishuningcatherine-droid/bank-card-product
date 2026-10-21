"""Training interface for the ranking layer (DESIGN §26.8).

Dataset: consented ``results_shown`` views ordered by the *baseline* (so positions mean the same thing in every
row), one row per product shown, label 1 when that product was opened or followed to the bank in the same view.
Product features are read from today's published record. A pointwise logistic model is fitted on 80% of the views
(split by view id) and compared with the baseline order on the other 20% (NDCG@10 over views with a click). The
artifact records where its data came from; only artifacts from real events can pass the gates.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankrec.api.repository import Repository
from bankrec.db.analytics import RankingEvent
from bankrec.rank.features import FEATURES, features

CLICKS = ("result_opened", "official_link_clicked")


@dataclass
class Row:
    list_id: str
    product_id: str
    position: int
    x: dict[str, float]
    y: int


def build_dataset(
    session: Session, product_type: str, now: datetime, *, allow_test_only: bool = False
) -> list[Row]:
    events = session.scalars(
        select(RankingEvent).where(
            RankingEvent.product_type == product_type, RankingEvent.ranker == "baseline"
        )
    ).all()
    shown: dict[str, list[str]] = {}
    clicked: dict[str, set[str]] = defaultdict(set)
    for e in events:
        if e.event == "results_shown" and e.shown:
            shown[str(e.list_id)] = list(e.shown)
        elif e.event in CLICKS and e.product_id:
            clicked[str(e.list_id)].add(e.product_id)
    repo = Repository(session, allow_test_only=allow_test_only)
    cache: dict[str, Any] = {}
    rows = []
    for lid, ids in shown.items():
        for pos, pid in enumerate(ids, start=1):
            if pid not in cache:
                cache[pid] = repo.get(pid, now)
            p = cache[pid]
            if p is None:
                continue
            rows.append(Row(lid, pid, pos, features(p, pos), int(pid in clicked.get(lid, set()))))
    return rows


def _holdout(list_id: str) -> bool:
    return int(hashlib.sha1(list_id.encode()).hexdigest(), 16) % 5 == 0  # noqa: S324 (split, not security)


def fit(rows: Iterable[Row], *, epochs: int = 300, lr: float = 0.5, l2: float = 1e-3) -> dict[str, float]:
    data = list(rows)
    w = dict.fromkeys(FEATURES, 0.0)
    n = max(1, len(data))
    for _ in range(epochs):
        grad = dict.fromkeys(FEATURES, 0.0)
        for r in data:
            z = sum(w[k] * r.x[k] for k in FEATURES)
            p = 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))
            for k in FEATURES:
                grad[k] += (p - r.y) * r.x[k]
        for k in FEATURES:
            w[k] -= lr * (grad[k] / n + l2 * w[k])
    return w


def _ndcg10(ordered_labels: list[int]) -> float:
    def dcg(labels: list[int]) -> float:
        return sum(y / math.log2(i + 2) for i, y in enumerate(labels[:10]))

    ideal = dcg(sorted(ordered_labels, reverse=True))
    return dcg(ordered_labels) / ideal if ideal else 0.0


def evaluate(rows: Iterable[Row], weights: dict[str, float]) -> dict[str, float]:
    by_list: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_list[r.list_id].append(r)
    base, model = [], []
    for lst in by_list.values():
        if not any(r.y for r in lst):
            continue
        base.append(_ndcg10([r.y for r in sorted(lst, key=lambda r: r.position)]))
        score = lambda r: sum(weights.get(k, 0.0) * v for k, v in r.x.items())  # noqa: E731
        model.append(_ndcg10([r.y for r in sorted(lst, key=lambda r: (-score(r), r.position))]))
    k = max(1, len(base))
    return {
        "baseline_ndcg10": round(sum(base) / k, 4),
        "model_ndcg10": round(sum(model) / k, 4),
        "eval_lists": len(base),
    }


def train(
    rows: list[Row], *, product_type: str, data_source: str, now: datetime, model_id: str
) -> dict[str, Any]:
    """The artifact: weights, training facts and held-out metrics. ``data_source`` is "events" only for rows built
    from recorded consented events; anything else can never pass the deployment gates."""
    train_rows = [r for r in rows if not _holdout(r.list_id)]
    test_rows = [r for r in rows if _holdout(r.list_id)]
    w = fit(train_rows)
    lists = {r.list_id for r in rows}
    clicked = {r.list_id for r in rows if r.y}
    return {
        "id": model_id,
        "kind": "linear_logistic",
        "product_types": [product_type],
        "features": FEATURES,
        "weights": {k: round(v, 6) for k, v in w.items()},
        "training": {
            "data_source": data_source,
            "trained_at": now.isoformat(),
            "n_rows": len(rows),
            "n_lists": len(lists),
            "n_clicked_lists": len(clicked),
            "holdout_share": 0.2,
        },
        "metrics": evaluate(test_rows, w),
        "approved_by": None,
    }
