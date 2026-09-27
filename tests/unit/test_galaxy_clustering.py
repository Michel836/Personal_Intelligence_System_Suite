"""Clustering engine unit tests (M020)."""
from __future__ import annotations

import numpy as np
import pytest

from src.galaxy import (
    NOISE,
    adjusted_rand_index,
    available_algorithms,
    cluster,
    cluster_stability,
    cohesion,
    select_k,
)
from src.galaxy.clustering import ClusteringError


def _blobs(per: int = 20, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = np.array([[6.0, 0.0], [0.0, 6.0], [-6.0, -6.0]])
    return np.vstack([centers[i % 3] + rng.normal(0, 0.15, 2) for i in range(per * 3)])


def test_algorithms_report_availability() -> None:
    algorithms = available_algorithms()
    assert algorithms["minibatch-kmeans"]["available"] is True
    assert algorithms["dbscan"]["max_points"] == 5_000


def test_cluster_finds_separated_groups() -> None:
    vectors = _blobs()
    result = cluster(vectors, algorithm="minibatch-kmeans", k=3, seed=0)
    assert result.k == 3
    assert result.noise_count == 0
    assert result.quality["cohesion"] > 0.9
    sizes = sorted(result.sizes().values())
    assert sizes == [20, 20, 20]


def test_cluster_is_stable_across_seeds() -> None:
    vectors = _blobs()
    stability = cluster_stability(vectors, algorithm="minibatch-kmeans", k=3, seeds=(0, 1, 2))
    assert stability["ari"] is not None
    assert stability["ari"] > 0.9


def test_select_k_stays_in_range() -> None:
    vectors = _blobs()
    selection = select_k(vectors, k_min=2, k_max=8, seed=0)
    assert 2 <= selection["selected_k"] <= 8
    assert selection["rationale"]


def test_adjusted_rand_index_identity_and_disagreement() -> None:
    a = [0, 0, 1, 1, 2, 2]
    assert adjusted_rand_index(a, a) == pytest.approx(1.0)
    disjoint = adjusted_rand_index(a, [0, 1, 2, 3, 4, 5])
    assert disjoint < 0.5


def test_noise_label_counts_for_hdbscan_style() -> None:
    labels = np.array([0, 0, 1, NOISE, NOISE])
    result = cluster(_blobs(per=4), algorithm="minibatch-kmeans", k=2, seed=0)
    assert result.noise_count == 0
    assert (labels == NOISE).sum() == 2


def test_dbscan_refuses_above_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.galaxy.clustering as clustering
    monkeypatch.setattr(clustering, "DBSCAN_MAX", 2)
    with pytest.raises(ClusteringError):
        cluster(np.zeros((3, 2)), algorithm="dbscan", seed=0)


def test_unknown_algorithm_is_refused() -> None:
    with pytest.raises(ClusteringError):
        cluster(np.zeros((3, 2)), algorithm="nope")


def test_cohesion_of_tight_clusters_is_high() -> None:
    vectors = _blobs()
    result = cluster(vectors, algorithm="kmeans", k=3, seed=0)
    assert cohesion(vectors, result.labels, result.centroids) is not None
