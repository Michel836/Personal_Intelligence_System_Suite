"""Galaxy persistence unit tests (M020)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.galaxy import GalaxyStore, freshness_signature, new_run_id, vector_namespace


@pytest.fixture()
def store(tmp_path: Path) -> GalaxyStore:
    return GalaxyStore(DatabaseManager(tmp_path / "store.db"))


def test_schema_tables_are_additive_and_rebuildable(store: GalaxyStore) -> None:
    info = store.rebuildable()
    assert info["drop_safe"] is True
    assert "galaxy_cluster_runs" in info["derived_tables"]
    with store.db.get_connection() as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"galaxy_cluster_runs", "galaxy_cluster_members", "galaxy_topics",
            "galaxy_projection_runs", "galaxy_projection_points"} <= names


def test_cluster_run_roundtrip_and_freshness(store: GalaxyStore) -> None:
    run_id = new_run_id("clu")
    freshness = freshness_signature(store.db, model_key="m", dim=8, store_count=10)
    store.save_cluster_run(run_id=run_id, algorithm="minibatch-kmeans",
                           params={"k": 3}, model_key="m", dim=8, freshness=freshness,
                           source_scope={"kind": "all"}, input_count=10, collapsed_count=0,
                           k=3, noise_count=0, quality={"cohesion": 0.9}, software_version="m020.1")
    store.save_members(run_id, [(1, 0, 0.9), (2, 0, 0.8), (3, 1, 0.7)])
    run = store.cluster_run(run_id)
    assert run is not None
    assert run["params"] == {"k": 3}
    assert store.run_status(run, current_freshness=freshness)["status"] == "FRESH"
    assert store.run_status(run, current_freshness="different")["status"] == "STALE"
    assert len(store.cluster_members(run_id, cluster_id=0)) == 2
    assert store.latest_cluster_run()["run_id"] == run_id


def test_projection_run_and_points(store: GalaxyStore) -> None:
    run_id = new_run_id("prj")
    store.save_projection_run(run_id=run_id, method="pca", params={"seed": 0},
                              model_key="m", dim=8, freshness="f",
                              source_scope={"kind": "all"}, input_count=2, sampled=False,
                              software_version="m020.1")
    store.save_projection_points(run_id, [(1, 0.1, 0.2, 0), (2, 0.3, 0.4, 1)])
    points = store.projection_points(run_id)
    assert len(points) == 2
    assert store.projection_run(run_id)["method"] == "pca"


def test_vector_namespace_is_model_and_dimension_bound() -> None:
    assert vector_namespace("bge-m3", 1024) == "bge-m3:1024"
    assert vector_namespace("bge-m3", 1024) != vector_namespace("bge-m3", 768)
