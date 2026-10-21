"""Rankers. ``BaselineRanker`` keeps the deterministic order; ``LinearRanker`` re-orders it with a trained model, and
is used only when its artifact passes every gate in config/ranking.yaml (DESIGN §26.8)."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from bankrec.rank.features import FEATURES, features
from bankrec.recommend.models import RecommendResponse
from bankrec.settings import CONFIG_DIR, REPO_ROOT

log = logging.getLogger("bankrec.rank")


class Ranker(Protocol):
    id: str

    def rerank(self, resp: RecommendResponse) -> RecommendResponse: ...


class BaselineRanker:
    id = "baseline"

    def rerank(self, resp: RecommendResponse) -> RecommendResponse:
        return resp.model_copy(update={"ranker": self.id})


@dataclass
class LinearRanker:
    id: str
    weights: dict[str, float]
    product_types: list[str] = field(default_factory=list)

    def score(self, x: dict[str, float]) -> float:
        z = sum(self.weights.get(k, 0.0) * v for k, v in x.items())
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))

    def rerank(self, resp: RecommendResponse) -> RecommendResponse:
        if self.product_types and resp.product_type not in self.product_types:
            return BaselineRanker().rerank(resp)
        scored = [(self.score(features(r.product, r.rank)), r.rank, r) for r in resp.results]
        ordered = [
            r.model_copy(update={"rank": n})
            for n, (_, _, r) in enumerate(sorted(scored, key=lambda t: (-t[0], t[1])), 1)
        ]
        return resp.model_copy(update={"results": ordered, "ranker": self.id})


def policy() -> dict[str, Any]:
    return dict(yaml.safe_load((CONFIG_DIR / "ranking.yaml").read_text(encoding="utf-8")))


def gate_failures(art: dict[str, Any], pol: dict[str, Any]) -> list[str]:
    """Why an artifact may not be the active ranker (empty = allowed)."""
    g = pol.get("gates", {})
    meta, metrics = art.get("training", {}), art.get("metrics", {})
    out = []
    if meta.get("data_source") != "events":
        out.append("not trained on real consented events")
    if int(meta.get("n_lists", 0)) < int(g.get("min_lists", 1000)):
        out.append(f"only {meta.get('n_lists', 0)} results views (need {g.get('min_lists', 1000)})")
    if int(meta.get("n_clicked_lists", 0)) < int(g.get("min_clicked_lists", 200)):
        out.append(
            f"only {meta.get('n_clicked_lists', 0)} views with a click (need {g.get('min_clicked_lists', 200)})"
        )
    if g.get("must_beat_baseline", True) and not (
        float(metrics.get("model_ndcg10", 0)) > float(metrics.get("baseline_ndcg10", 1))
    ):
        out.append("does not beat the baseline on held-out data")
    if g.get("require_owner_approval", True) and not art.get("approved_by"):
        out.append("not approved by the owner")
    if sorted(art.get("features", [])) != sorted(FEATURES):
        out.append("feature set differs from this version")
    return out


@lru_cache(maxsize=1)
def active_ranker() -> Ranker:
    pol = policy()
    name = str(pol.get("active") or "baseline")
    if name == "baseline":
        return BaselineRanker()
    try:
        art = json.loads((REPO_ROOT / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("ranking model unreadable; using the baseline", extra={"model": name})
        return BaselineRanker()
    if bad := gate_failures(art, pol):
        log.warning("ranking model refused; using the baseline", extra={"model": name, "reasons": bad})
        return BaselineRanker()
    return LinearRanker(
        id=str(art["id"]),
        weights={k: float(v) for k, v in art["weights"].items()},
        product_types=list(art.get("product_types", [])),
    )


def load_artifact(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))
