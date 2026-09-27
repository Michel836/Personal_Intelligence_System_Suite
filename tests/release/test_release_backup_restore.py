"""Release backup -> verify -> restore -> full round-trip (M021 hard gate)."""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.dedup import DedupStore
from src.intel import IntelStore
from src.ops.backup import create_backup, restore_backup, verify_backup
from src.reports import DossierService, ExportService, ReportKind


def _counts(db) -> dict[str, int]:
    with db.get_connection() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("files", "content_hashes", "doc_language", "doc_pii",
                          "dossiers", "galaxy_cluster_runs", "galaxy_topics")}


def test_backup_restore_roundtrip_preserves_state(release_env, tmp_path, monkeypatch) -> None:
    db = release_env.db
    # Create the derived state that must survive: dossier, report, galaxy run.
    dossier = DossierService(db).create("Backup dossier",
                                        file_ids=[release_env.file_id("docs/alpha_finance.txt")])
    export = ExportService(db, out_dir=tmp_path / "exports")
    export.save_definition(export.create_definition(
        ReportKind.SEARCH.value, "Backup report", query={"query": "finance"}))
    from src.galaxy import GalaxyService
    from src.intelligence.embedding_store import EmbeddingMatrixStore
    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=release_env.store_dir)
    assert store.load()
    built = GalaxyService(db, embedding_store=store).build_clusters(
        scope={"kind": "all"}, k=4, persist=True)
    run_id = built["run_id"]

    before = _counts(db)
    backup = create_backup(db, out_dir=tmp_path / "backups", include_semantic=True)
    assert Path(backup.archive_path).exists()
    verification = verify_backup(backup.archive_path)
    assert verification["ok"] is True
    assert verification["schema_compatible"] is True
    assert verification["manifest"]["backup_id"] == backup.backup_id

    restored_dir = tmp_path / "restored"
    result = restore_backup(backup.archive_path, target_db=restored_dir / "release.db",
                            restore_semantic=True, semantic_target=restored_dir / "store",
                            confirm=True)
    assert result.status == "RESTORED"
    assert "semantic" in result.restored
    restored_db = DatabaseManager(restored_dir / "release.db")
    with restored_db.get_connection() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    after = _counts(restored_db)
    assert after == before

    # Lexical + dedup + intel + dossier definitions survive.
    finance_id = release_env.file_id("docs/alpha_finance.txt")
    assert restored_db.search_files("Bank payment accounting")
    assert DedupStore(restored_db).get_hash(finance_id) is not None
    assert IntelStore(restored_db).get_language(finance_id) is not None
    assert DossierService(restored_db).get(dossier["dossier_id"]) is not None
    assert ExportService(restored_db).store.list_definitions(limit=10)

    # Semantic store restored: query against the restored namespace.
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(restored_dir / "store"))
    from src.intelligence.semantic_search import SemanticSearchEngine
    engine = SemanticSearchEngine(restored_db, embedding_gen=release_env.generator)
    hits = engine.semantic_search("finance invoice bank", limit=10)
    assert hits and finance_id in {int(r["id"]) for r in hits}

    # Galaxy/cluster metadata survives and is still FRESH.
    from src.galaxy import GalaxyService
    restored_store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                          base_dir=restored_dir / "store")
    assert restored_store.load()
    service = GalaxyService(restored_db, embedding_store=restored_store)
    assert service.store.cluster_run(run_id) is not None
    assert service.status()["latest_cluster_run"]["status"] == "FRESH"

    # A brand-new report can be generated from the restored database.
    new_definition = export.create_definition(ReportKind.SEARCH.value, "Post-restore",
                                              query={"query": "compiler"})
    generated = export.generate(new_definition, formats=("HTML", "JSON"))
    assert generated.artifacts and all(Path(a.path).exists() for a in generated.artifacts)


def test_semantic_rebuild_succeeds_when_store_not_restored(release_env, tmp_path,
                                                           monkeypatch) -> None:
    db = release_env.db
    backup = create_backup(db, out_dir=tmp_path / "backups", include_semantic=True)
    restored = tmp_path / "rebuild"
    result = restore_backup(backup.archive_path, target_db=restored / "release.db",
                            restore_semantic=False, confirm=True)
    assert result.status == "RESTORED"
    assert "semantic" not in result.restored

    # Point at an empty store directory and rebuild from the restored DB.
    empty_store = restored / "empty-store"
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(empty_store))
    monkeypatch.setenv("PIS_EMBEDDING_CACHE_DIR", str(restored / "embcache"))
    rebuilt_db = DatabaseManager(restored / "release.db")
    from src.intelligence.semantic_search import SemanticSearchEngine
    engine = SemanticSearchEngine(rebuilt_db, embedding_gen=release_env.generator)
    refresh = engine.refresh(batch_size=256)
    assert refresh["available"] is True
    assert refresh["store_count"] > 0
    assert engine.semantic_search("finance invoice bank", limit=5)


def test_corrupt_backup_is_refused(release_env, tmp_path) -> None:
    backup = create_backup(release_env.db, out_dir=tmp_path / "backups",
                           include_semantic=False)
    corrupt = tmp_path / "corrupt.tar.gz"
    data = Path(backup.archive_path).read_bytes()
    corrupt.write_bytes(data[: len(data) // 2])  # truncated
    verification = verify_backup(corrupt)
    assert verification["ok"] is False
    result = restore_backup(corrupt, target_db=tmp_path / "x.db", confirm=True)
    assert result.status == "REFUSED"


def test_restore_requires_confirmation(release_env, tmp_path) -> None:
    backup = create_backup(release_env.db, out_dir=tmp_path / "backups",
                           include_semantic=False)
    result = restore_backup(backup.archive_path, target_db=tmp_path / "y.db")
    assert result.status == "REFUSED"
