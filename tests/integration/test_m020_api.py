"""Galaxy/cluster/topic/context API integration + privacy (M020)."""
from __future__ import annotations

import pytest

pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from src.api import API_SCHEMA, create_app  # noqa: E402


@pytest.fixture()
def client(galaxy_env, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(galaxy_env.base_dir))
    return TestClient(create_app(galaxy_env.db))


def test_index_lists_galaxy_endpoints(client: TestClient) -> None:
    body = client.get("/api/v1").json()
    assert body["schema"] == API_SCHEMA
    endpoints = body["data"]["endpoints"]
    assert any(e.endswith("/galaxy") for e in endpoints)
    assert any(e.endswith("/clusters") for e in endpoints)
    assert any(e.endswith("/topics") for e in endpoints)


def test_galaxy_payload_is_bounded_and_paths_masked(client: TestClient) -> None:
    resp = client.get("/api/v1/galaxy?scope=all&k=5&limit=100")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["available"] is True
    assert len(data["points"]) <= 100
    assert "/synthetic/" not in resp.text


def test_galaxy_unknown_scope_is_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/galaxy?scope=bogus")
    assert resp.status_code == 400


def test_clusters_and_topics_endpoints(client: TestClient, galaxy_env) -> None:
    built = galaxy_env.service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    clusters = client.get("/api/v1/clusters?build=1")
    assert clusters.status_code == 200
    data = clusters.json()["data"]
    assert data["available"] is True
    assert data["run_id"] == built["run_id"]
    assert data["clusters"]
    topics = client.get("/api/v1/topics")
    assert topics.status_code == 200
    assert topics.json()["data"]["topics"]


def test_cluster_detail_masks_members(client: TestClient, galaxy_env) -> None:
    built = galaxy_env.service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    run_id = built["run_id"]
    cluster_id = int(built["result"].labels[0])
    galaxy_env.service.build_topics(run_id)
    resp = client.get(f"/api/v1/clusters/{run_id}/{cluster_id}")
    assert resp.status_code == 200
    assert "/synthetic/" not in resp.text
    assert resp.json()["data"]["size"] > 0
    assert client.get("/api/v1/clusters/nope/0").status_code == 404


def test_context_endpoint_masks_paths_and_unknown_is_404(client: TestClient) -> None:
    resp = client.get("/api/v1/context/1")
    assert resp.status_code == 200
    assert "/synthetic/" not in resp.text
    assert client.get("/api/v1/context/999999").status_code == 404
