#!/usr/bin/env python3
"""Run the release acceptance journey and write aggregate evidence (M021).

Builds the deterministic public-safe corpus in a trial workspace, drives the
canonical pipeline (scan → extract → intel → dedup/versions → semantic), exercises
dossier/report/export and galaxy/topics, performs a backup → verify → restore
round-trip, and records timings/counts only. No private data and no production DB
or source corpus is touched.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def _timed(label: str, timings: dict[str, float], fn: Any) -> Any:
    t0 = time.perf_counter()
    result = fn()
    timings[label] = round(time.perf_counter() - t0, 3)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", default="/home/chu/.pis-trials/m021/workspace")
    ap.add_argument("--out", default="/home/chu/.pis-trials/m021/evidence/release_acceptance.json")
    args = ap.parse_args(argv)

    import os
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PIS_EMBEDDING_STORE_DIR"] = str(work / "store")
    os.environ["PIS_EMBEDDING_CACHE_DIR"] = str(work / "embcache")
    os.environ["PIS_EXPORT_DIR"] = str(work / "exports")
    os.environ["PIS_OCR_ENABLED"] = "0"
    os.environ["PIS_REMOTE_CONTENT_POLICY"] = "never"

    from src.archives.indexer import ArchiveIndexer
    from src.archives.inspector import ArchiveBudget
    from src.core.database import DatabaseManager
    from src.core.scan_service import ScanRequest, ScanService
    from src.core.volume import VolumeInfo
    from src.dedup import ContentHasher, VersionTracker
    from src.galaxy import GalaxyService
    from src.ingest.pipeline import IngestionPipeline
    from src.intel import IntelPipeline
    from src.intelligence.embedding_store import EmbeddingMatrixStore
    from src.intelligence.semantic_search import SemanticSearchEngine
    from src.ops.backup import create_backup, restore_backup, verify_backup
    from src.reports import DossierService, ExportService, ReportKind
    from tests.release.corpus import build_acceptance_corpus
    from tests.release.fakes import HashingEmbeddingGenerator

    report: dict[str, Any] = {"corpus": {}, "timings": {}, "stages": {}, "backup": {}}
    timings: dict[str, float] = report["timings"]

    corpus = _timed("corpus_build", timings, lambda: build_acceptance_corpus(work / "corpus"))
    report["corpus"] = {"entries": len(corpus.entries),
                        "kinds": sorted(corpus.by_kind())}

    db_path = work / "release.db"
    if db_path.exists():
        db_path.unlink()
    db = DatabaseManager(db_path)

    scanned = _timed("scan", timings, lambda: ScanService(db).run(ScanRequest(
        root=corpus.root, volume=VolumeInfo(stable_key="rc", device="rc",
                                            mountpoint=str(corpus.root), is_available=True))))
    report["stages"]["scan"] = {"status": scanned.status, "seen": scanned.files_seen,
                                "upserted": scanned.files_upserted}

    def _index_archive() -> None:
        with db.get_connection() as conn:
            row = conn.execute("SELECT id, path, volume_id FROM files WHERE extension='.zip'").fetchone()
        if row is not None:
            ArchiveIndexer(db).index_archive(int(row["id"]), str(row["path"]),
                                             budget=ArchiveBudget(), volume_id=row["volume_id"])

    _timed("archive_index", timings, _index_archive)

    extracted = _timed("extract", timings, lambda: IngestionPipeline(db).run(
        min_size=1, max_size=50 * 1024 * 1024))
    report["stages"]["extract"] = {"counts": extracted["counts"]}

    intel = _timed("intel", timings, lambda: IntelPipeline(db).run(min_chars=10, include_members=True))
    report["stages"]["intel"] = {"processed": intel["processed"], "pii_docs": intel["pii_docs"]}

    _timed("hash_backfill", timings, lambda: ContentHasher(db).backfill(
        min_size=1, max_size=50 * 1024 * 1024, include_members=True))
    _timed("versions", timings, lambda: VersionTracker(db).build(include_members=False))

    generator = HashingEmbeddingGenerator(dim=64)
    engine = SemanticSearchEngine(db, embedding_gen=generator)
    refresh = _timed("semantic_refresh", timings, lambda: engine.refresh(batch_size=128))
    report["stages"]["semantic"] = refresh
    hits = _timed("semantic_search", timings,
                  lambda: engine.semantic_search("finance invoice bank", limit=10))
    report["stages"]["semantic_hits"] = len(hits)

    _timed("dossier", timings, lambda: DossierService(db).create(
        "RC acceptance", file_ids=[int(r["id"]) for r in db.search_files(None, limit=5)]))
    exporter = ExportService(db, out_dir=work / "exports")
    definition = exporter.create_definition(ReportKind.SEARCH.value, "RC acceptance report",
                                            query={"query": "finance"})
    generated = _timed("report_export", timings, lambda: exporter.generate(
        definition, formats=("HTML", "JSON")))
    report["stages"]["report"] = {"artifacts": [a.format for a in generated.artifacts],
                                  "sources": len(generated.ir.sources)}

    store = EmbeddingMatrixStore("release-hash", "release-hash-embedding", 64,
                                 base_dir=work / "store")
    store.load()
    service = GalaxyService(db, embedding_store=store)
    galaxy = _timed("galaxy", timings, lambda: service.galaxy(
        scope={"kind": "all"}, method="pca", k=5, persist=False))
    built = _timed("clustering", timings, lambda: service.build_clusters(
        scope={"kind": "all"}, k=5, persist=True))
    topics = _timed("topics", timings, lambda: service.build_topics(built["run_id"]))
    report["stages"]["galaxy"] = {"available": galaxy["available"],
                                  "points": len(galaxy["points"]),
                                  "clusters": len(topics), "run_id": built["run_id"]}

    backup = _timed("backup", timings, lambda: create_backup(db, out_dir=work / "backups"))
    verification = _timed("verify", timings, lambda: verify_backup(backup.archive_path))
    restore = _timed("restore", timings, lambda: restore_backup(
        backup.archive_path, target_db=work / "restored" / "release.db",
        restore_semantic=False, confirm=True))
    restored_db = DatabaseManager(work / "restored" / "release.db")
    with restored_db.get_connection() as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    report["backup"] = {"verify_ok": verification.get("ok"),
                        "schema_compatible": verification.get("schema_compatible"),
                        "restore_status": restore.status,
                        "restore_integrity": integrity,
                        "restored_search": bool(restored_db.search_files("finance"))}
    with db.get_connection() as conn:
        report["counts"] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                            for t in ("files", "content_hashes", "doc_language", "doc_pii",
                                      "dossiers", "galaxy_cluster_runs", "galaxy_topics")}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
