"""Ranking layer and training interface (DESIGN §26.8). Example Bank data and synthetic events only."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

import pytest

from bankrec.db.analytics import RankingEvent
from bankrec.rank.features import FEATURES
from bankrec.rank.rankers import BaselineRanker, LinearRanker, gate_failures, policy
from bankrec.rank.train import Row, build_dataset, train
from bankrec.recommend import recommend
from bankrec.recommend.models import CheckingRequest
from tests.integration.helpers import registry, run

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def synthetic_rows(n_lists: int, seed: int = 7) -> list[Row]:
    """Views of 5 products where people mostly click the product with a public offer, wherever it is placed."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n_lists):
        lid = f"list-{i}"
        offer_at = rnd.randint(1, 5)
        for pos in range(1, 6):
            has = 1.0 if pos == offer_at else 0.0
            x = {
                "bias": 1.0,
                "inv_position": 1 / pos,
                "has_public_offer": has,
                "log_bonus_dollars": 5.0 * has,
                "fee_dollars_100": 0.0,
            }
            y = int(rnd.random() < (0.6 if has else 0.05))
            rows.append(Row(lid, f"p{pos}", pos, x, y))
    return rows


def test_training_learns_but_synthetic_data_can_never_deploy() -> None:
    art = train(
        synthetic_rows(1500), product_type="credit_card", data_source="synthetic", now=NOW, model_id="t"
    )
    assert art["features"] == FEATURES and art["weights"]["has_public_offer"] > 0
    assert art["metrics"]["model_ndcg10"] > art["metrics"]["baseline_ndcg10"]
    bad = gate_failures(art, policy())
    assert "not trained on real consented events" in bad and "not approved by the owner" in bad


def test_gates_need_real_data_volume_a_win_and_owner_approval() -> None:
    art = train(synthetic_rows(1500), product_type="credit_card", data_source="events", now=NOW, model_id="t")
    assert gate_failures(art, policy()) == ["not approved by the owner"]
    assert gate_failures({**art, "approved_by": "owner"}, policy()) == []
    small = train(synthetic_rows(50), product_type="credit_card", data_source="events", now=NOW, model_id="s")
    assert any("results views" in g for g in gate_failures({**small, "approved_by": "owner"}, policy()))
    worse = {**art, "approved_by": "owner", "metrics": {"baseline_ndcg10": 0.8, "model_ndcg10": 0.7}}
    assert gate_failures(worse, policy()) == ["does not beat the baseline on held-out data"]


def test_default_ranker_is_the_baseline_and_a_model_only_reorders() -> None:
    from bankrec.rank.rankers import active_ranker

    assert policy()["active"] == "baseline" and isinstance(active_ranker(), BaselineRanker)


@pytest.mark.db
def test_dataset_from_consented_events_and_reorder(session, settings) -> None:  # type: ignore[no-untyped-def]
    from bankrec.api.repository import Repository

    run(session, settings, registry())
    products = Repository(session, allow_test_only=True).all_of_type("checking", NOW)
    resp = recommend(products, CheckingRequest(product_type="checking", max_monthly_fee=50), NOW)
    ids = [r.product.id for r in resp.results]
    assert len(ids) >= 2
    anon, lid = uuid.uuid4(), uuid.uuid4()
    session.add(
        RankingEvent(
            anon_id=anon,
            list_id=lid,
            event="results_shown",
            product_type="checking",
            shown=ids,
            ranker="baseline",
            occurred_hour=NOW,
        )
    )
    session.add(
        RankingEvent(
            anon_id=anon,
            list_id=lid,
            event="official_link_clicked",
            product_type="checking",
            product_id=ids[-1],
            position=len(ids),
            ranker="baseline",
            occurred_hour=NOW,
        )
    )
    session.commit()
    rows = build_dataset(session, "checking", NOW, allow_test_only=True)
    assert [(r.product_id, r.position, r.y) for r in rows] == [
        (pid, n, int(pid == ids[-1])) for n, pid in enumerate(ids, 1)
    ]
    # a model that strongly prefers lower positions reverses the baseline order; ranks are renumbered
    flip = LinearRanker(id="flip", weights={"inv_position": -10.0})
    out = flip.rerank(resp)
    assert out.ranker == "flip" and [r.product.id for r in out.results] == ids[::-1]
    assert [r.rank for r in out.results] == list(range(1, len(ids) + 1))
    assert BaselineRanker().rerank(resp).results == resp.results
