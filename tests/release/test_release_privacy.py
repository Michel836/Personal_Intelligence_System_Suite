"""Release privacy acceptance: local-only + no raw PII where masking applies (M021)."""
from __future__ import annotations

import socket
from pathlib import Path

from src.ai.providers.config import AIConfig
from src.ai.providers.policy import RemoteContentPolicy
from src.ai.providers.service import AIService
from src.reports import ExportService, PrivacyMode, ReportKind

RAW_EMAIL = "release.fixture@example.test"
RAW_IBAN = "FR7630006000011234567890189"


def test_policy_matrix() -> None:
    never = RemoteContentPolicy.from_env("never")
    assert never.allows_remote is False
    metadata = RemoteContentPolicy.from_env("metadata_only")
    assert metadata.allows_remote is True and metadata.allows_extracted_text is False
    text = RemoteContentPolicy.from_env("extracted_text")
    assert text.allows_extracted_text is True and text.allows_full_context is False
    full = RemoteContentPolicy.from_env("full_context")
    assert full.allows_full_context is True
    # Unknown values never silently relax the policy.
    assert RemoteContentPolicy.from_env("definitely-not-a-policy") is RemoteContentPolicy.NEVER


def test_never_policy_blocks_remote_embedding_selection(monkeypatch) -> None:
    monkeypatch.setenv("PIS_REMOTE_CONTENT_POLICY", "never")
    service = AIService(AIConfig(mode="auto", content_policy=RemoteContentPolicy.NEVER))
    assert service.remote_embedding_generator(requires_text=True) is None
    assert service.remote_embedding_generator(requires_text=False) is None


def test_zero_remote_traffic_during_canonical_operations(release_env, monkeypatch) -> None:
    remote_hosts: list[str] = []
    posts: list[str] = []

    real_connect = socket.create_connection

    def guarded_connect(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        remote_hosts.append(host)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"remote connection attempted under 'never': {host}")
        return real_connect(address, *args, **kwargs)

    try:
        import requests

        def guarded_post(_self, url, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            posts.append(str(url))
            raise AssertionError(f"remote POST attempted under 'never': {url}")

        monkeypatch.setattr(requests.Session, "post", guarded_post)
        monkeypatch.setattr(requests, "post", guarded_post, raising=False)
    except Exception:  # noqa: BLE001 - requests is always present here
        pass

    monkeypatch.setattr(socket, "create_connection", guarded_connect)

    db = release_env.db
    # Exercise every content-bearing path.
    db.search_files("finance bank invoice", limit=10)
    release_env.engine.semantic_search("finance invoice bank", limit=10)
    from src.intel.redact import redacted_preview
    redacted_preview(f"Contact {RAW_EMAIL} IBAN {RAW_IBAN}", max_chars=200)

    exporter = ExportService(db, out_dir=release_env.root / "priv-exports")
    definition = exporter.create_definition(ReportKind.SEARCH.value, "Privacy",
                                            query={"query": "finance"})
    exporter.generate(definition, formats=("HTML", "JSON"))

    from src.galaxy import GalaxyService
    from src.intelligence.embedding_store import EmbeddingMatrixStore
    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=release_env.store_dir)
    assert store.load()
    service = GalaxyService(db, embedding_store=store)
    service.galaxy(scope={"kind": "all"}, method="pca", k=4, persist=False)
    finance_id = release_env.file_id("docs/alpha_finance.txt")
    service.document_context(finance_id)

    assert posts == [], f"no remote POST expected, saw {posts}"
    assert all(h in ("127.0.0.1", "::1", "localhost") for h in remote_hosts)


def test_mask_pii_report_and_topic_labels_do_not_leak(release_env) -> None:
    db = release_env.db
    exporter = ExportService(db, out_dir=release_env.root / "priv-exports")
    pii_id = release_env.file_id("docs/pii_fixture.txt")
    definition = exporter.create_definition(
        ReportKind.SEARCH.value, "Masked PII", document_ids=[pii_id],
        privacy_mode=PrivacyMode.MASK_PII.value)
    result = exporter.generate(definition, formats=("HTML",))
    html = Path(next(a.path for a in result.artifacts if a.format == "HTML")).read_text(
        encoding="utf-8")
    assert RAW_EMAIL not in html
    assert RAW_IBAN not in html

    from src.galaxy import GalaxyService
    from src.intelligence.embedding_store import EmbeddingMatrixStore
    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=release_env.store_dir)
    assert store.load()
    service = GalaxyService(db, embedding_store=store)
    run_id = service.build_clusters(scope={"kind": "all"}, k=4, persist=True)["run_id"]
    for topic in service.build_topics(run_id):
        assert RAW_EMAIL not in topic.label and "@" not in topic.label
        for term, _weight in topic.terms:
            assert "@" not in term

    # document_context returns only masked PII metadata.
    context = service.document_context(pii_id)
    assert RAW_EMAIL not in str(context)
    assert context["privacy"]["raw_pii_exposed"] is False
