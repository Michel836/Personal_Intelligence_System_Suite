"""Projection engine unit tests (M020)."""
from __future__ import annotations

import numpy as np
import pytest

from src.galaxy import available_methods, project
from src.galaxy.projection import TSNE_MAX, ProjectionError


def _blobs(seed: int = 0) -> tuple[list[int], np.ndarray]:
    rng = np.random.default_rng(seed)
    centers = np.array([[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]])
    vectors = []
    ids = []
    for i in range(30):
        vector = centers[i % 3] + rng.normal(0, 0.1, 3)
        vectors.append(vector)
        ids.append(i + 1)
    return ids, np.asarray(vectors)


def test_available_methods_reports_pca_and_bounds() -> None:
    methods = available_methods()
    assert methods["pca"]["available"] is True
    assert methods["svd"]["available"] is True
    assert methods["tsne"]["max_points"] == TSNE_MAX
    assert set(methods) == {"pca", "svd", "umap", "tsne"}


def test_pca_is_deterministic_and_bounded() -> None:
    ids, vectors = _blobs()
    first = project(ids, vectors, method="pca", seed=1)
    second = project(ids, vectors, method="pca", seed=1)
    assert first.ids == ids
    assert first.coords.shape == (30, 2)
    assert np.allclose(first.coords, second.coords)
    assert first.method == "pca"
    assert "exploratory" in first.limitations


def test_pca_separates_distinct_blobs() -> None:
    ids, vectors = _blobs()
    result = project(ids, vectors, method="pca")
    coords = result.coords
    # Points of the same blob (stride 3) should be closer than across blobs.
    same = np.linalg.norm(coords[0] - coords[3])
    across = np.linalg.norm(coords[0] - coords[1])
    assert same < across


def test_svd_runs_and_matches_shape() -> None:
    ids, vectors = _blobs()
    result = project(ids, vectors, method="svd")
    assert result.coords.shape == (len(ids), 2)
    assert result.explained_variance


def test_single_point_is_safe() -> None:
    result = project([7], np.ones((1, 4)), method="pca")
    assert result.ids == [7]
    assert result.coords.shape == (1, 2)
    assert result.warnings


def test_unknown_method_is_refused() -> None:
    with pytest.raises(ProjectionError):
        project([1], np.ones((1, 3)), method="magic")


def test_tsne_refuses_large_input() -> None:
    vectors = np.zeros((TSNE_MAX + 1, 3))
    with pytest.raises(ProjectionError):
        project(list(range(len(vectors))), vectors, method="tsne")


def test_mismatched_ids_are_refused() -> None:
    with pytest.raises(ProjectionError):
        project([1, 2], np.ones((3, 3)), method="pca")
