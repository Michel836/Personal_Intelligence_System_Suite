"""Galaxy/cluster/topic/context service integration tests (M020)."""
from __future__ import annotations

from src.galaxy import GalaxyService, describe_stack, scale_tier


def test_scale_tiers_are_evidence_based() -> None:
    assert scale_tier(100) == "SMALL"
    assert scale_tier(10_000) == "MEDIUM"
    assert scale_tier(80_039) == "LARGE"
    stack = describe_stack()
    assert stack["projection"]["pca"]["available"] is True


def test_galaxy_points_payload_is_bounded_and_labelled(galaxy_env) -> None:
    payload = galaxy_env.service.galaxy(scope={"kind": "all"}, method="pca",
                                        color_by="cluster", k=5, persist=False)
    assert payload["available"] is True
    assert payload["tier"] == "SMALL"
    assert 0 < len(payload["points"]) <= 34
    assert payload["clusters"]
    assert all("x" in p and "y" in p for p in payload["points"])
    assert "exploratory" in " ".join(payload["meta"]["warnings"])


def test_build_clusters_topics_and_detail(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    built = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    run_id = built["run_id"]
    topics = service.build_topics(run_id)
    assert topics
    assert all(t.label for t in topics)
    detail = service.cluster_detail(run_id, topics[0].cluster_id)
    assert detail["size"] > 0
    assert detail["status"]["status"] == "FRESH"
    assert detail["topic"]["label"]


def test_collapse_duplicates_and_versions(galaxy_env) -> None:
    ids = list(range(1, 35))
    kept, detail = galaxy_env.service.collapse_ids(ids, exact=True, versions=True)
    assert detail["exact_removed"] == 1
    assert detail["version_removed"] == 1
    assert 31 not in kept or 32 not in kept
    assert not (33 in kept and 34 in kept)


def test_document_context_uses_canonical_services(galaxy_env) -> None:
    context = galaxy_env.service.document_context(1)
    assert context["document"]["id"] == 1
    assert "intel" in context
    assert "semantic_neighbors" in context
    assert context["privacy"]["raw_pii_exposed"] is False


def test_cluster_graph_and_topic_over_time(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    run_id = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)["run_id"]
    service.build_topics(run_id)
    graph = service.cluster_graph(run_id)
    assert graph["nodes"]
    assert len(graph["edges"]) <= graph["bounds"]["max_edges"]
    series = service.topic_over_time(run_id, group="month")
    assert series["date_source"] == "modified_at"
    assert series["series"]


def test_dossier_and_report_from_cluster(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    built = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)
    run_id = built["run_id"]
    cluster_id = int(built["result"].labels[0])
    dossier = service.create_dossier_from_cluster(run_id, cluster_id, "Cluster dossier")
    assert dossier["member_count"] > 0
    report = service.report_from_cluster(run_id, cluster_id, "Cluster report")
    assert report["report_id"].startswith("rpt_")


def test_incremental_reassign_and_stability(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    run_id = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)["run_id"]
    reassigned = service.incremental_reassign(run_id, new_ids=[1, 2])
    assert reassigned["assigned"] == 2
    stability = service.cluster_stability(run_id)
    assert stability["ari"] is None or -1.0 <= stability["ari"] <= 1.0


def test_scope_resolution_kinds(galaxy_env) -> None:
    service: GalaxyService = galaxy_env.service
    assert service.resolve_scope({"kind": "all"})
    assert service.resolve_scope({"kind": "prefix", "prefix": "/synthetic/legal"})
    assert service.resolve_scope({"kind": "file_ids", "ids": [1, 2, 3]}) == [1, 2, 3]
    assert service.resolve_scope({"kind": "date", "start": "2024-01-01", "end": "2024-12-31"})
