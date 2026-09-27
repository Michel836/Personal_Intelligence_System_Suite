"""M020 hostile review: freshness, namespace, duplicate dominance, bounds."""
from __future__ import annotations

import numpy as np
import pytest

from src.galaxy import GalaxyError, GalaxyService, cluster
from src.galaxy.clustering import ClusteringError
from src.intelligence.embedding_store import EmbeddingMatrixStore


def test_run_goes_stale_after_embedding_generation_changes(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    assert service.status()["latest_cluster_run"]["status"] == "FRESH"
    galaxy_env.db.bump_semantic_generation()
    assert service.status()["latest_cluster_run"]["status"] == "STALE"


def test_mixed_vector_namespace_is_detected(galaxy_env) -> None:
    galaxy_env.service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    other = EmbeddingMatrixStore("other-model", "other", 4, base_dir=galaxy_env.base_dir)
    other.save([1, 2], np.ones((2, 4), dtype=np.float32), hashes=["a", "b"])
    mixed = GalaxyService(galaxy_env.db, embedding_store=other)
    run = mixed.store.latest_cluster_run()
    assert run is not None
    assert mixed.store.run_status(run, current_freshness=mixed.current_freshness())["status"] == "STALE"


def test_collapse_prevents_duplicate_dominance(galaxy_env) -> None:
    raw = galaxy_env.service.build_clusters(scope={"kind": "all"}, k=5, persist=False)
    collapsed = galaxy_env.service.build_clusters(
        scope={"kind": "all"}, k=5, persist=False,
        collapse_duplicates=True, collapse_versions=True)
    assert collapsed["collapsed"] >= 2
    assert collapsed["result"].input_count < raw["result"].input_count


def test_missing_documents_leave_scope(galaxy_env) -> None:
    with galaxy_env.db.get_connection() as conn:
        conn.execute("UPDATE files SET state='MISSING' WHERE id=1")
        conn.commit()
    assert 1 not in galaxy_env.service.resolve_scope({"kind": "all"})


def test_unknown_run_is_refused(galaxy_env) -> None:
    with pytest.raises(GalaxyError):
        galaxy_env.service.build_topics("clu_does_not_exist")
    with pytest.raises(GalaxyError):
        galaxy_env.service.cluster_detail("clu_does_not_exist", 0)


def test_tsne_refused_on_large_corpus() -> None:
    from src.galaxy import project
    from src.galaxy.projection import ProjectionError

    vectors = np.zeros((3_000, 8), dtype=np.float32)
    with pytest.raises(ProjectionError):
        project(list(range(len(vectors))), vectors, method="tsne")


def test_dbscan_refused_at_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.galaxy.clustering as clustering
    monkeypatch.setattr(clustering, "DBSCAN_MAX", 5)
    with pytest.raises(ClusteringError):
        cluster(np.zeros((10, 2)), algorithm="dbscan")


def test_clustering_does_not_blow_up_on_medium_input() -> None:
    rng = np.random.default_rng(0)
    vectors = rng.normal(0, 1, (3000, 16)).astype(np.float32)
    result = cluster(vectors, algorithm="minibatch-kmeans", k=12, seed=0)
    assert result.k == 12
    assert sum(result.sizes().values()) == 3000
