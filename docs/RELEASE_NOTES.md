# Release Notes — v1.0.0-rc1 (M013–M020)

Mono-user, local-first personal intelligence system. This release candidate
consolidates eleven missions (M013–M020) into one canonical application. SQLite
is canonical; the source corpus is never modified.

## Major capabilities

* **Scale & freshness (M013):** read-only 250k preflight, deterministic corpus
  manifest, incremental indexing, semantic change tracking and crash recovery.
* **Duplicates, versions & related docs (M014):** content hashing, exact and
  bounded near-duplicate discovery, evidence-based version families,
  duplicate-aware reranking.
* **Intelligence & privacy (M015):** dependency-free FR/DE/EN language detection,
  entities, categories, validated PII detection with masked displays only, and a
  remote-content policy that is authoritative.
* **Timeline, relationship graph & prioritization (M016):** provenance-aware date
  sources, bounded relationship graph, transparent weighted priority.
* **Ingestion hardening (M017):** email/legacy/EPUB/CHM extraction, OCR
  hardening, deterministic outcome taxonomy and a bounded retry queue.
* **Dossiers & reports (M018):** STATIC/DYNAMIC dossiers, 8 report kinds,
  citations/provenance, HTML/JSON/PDF export with a reproducibility manifest and
  privacy modes.
* **Operations (M019):** canonical `pis` CLI, loopback REST API, doctor/health,
  bounded maintenance, application-consistent backup/restore, instance safety and
  an evidence-based pgvector **KEEP_CURRENT** decision.
* **Galaxy, clustering, topics & context (M020):** bounded 2D semantic galaxy,
  scalable clustering, evidence-backed c-TF-IDF topics, contextual document view,
  topic-over-time and overlays.

## Architecture decisions

* One canonical app (`src/ui/app.py`) with three profiles; no forked stacks.
* One canonical database (SQLite) and one vector backend (NumPy matrix store).
* Derived data is additive and rebuildable; no second corpus database.
* Every derived run records algorithm, parameters, vector namespace and freshness.
* No O(N²) all-pairs similarity; projections/clusters/metrics are bounded.
* Privacy is enforced at the provider boundary; profiles never relax it.

## Measured scale

* 80 039-vector store: projection 6.6 s, clustering 4.5 s, topics 3.3 s, peak
  service RSS ~2.0 GB; semantic no-change sweep O(1).
* Scan ~9 600 files/s, extraction ~82 docs/s (M010/M011 anchors), backup ~198 s
  for a 1.5 GB archive (M019).

## Privacy guarantees

* `PIS_REMOTE_CONTENT_POLICY=never` by default in every profile.
* No remote content traffic during canonical search/report/galaxy operations
  (release acceptance asserts zero remote connections).
* PII stored only as masked display + salted fingerprint; API masks paths/PII.
* Source files are never modified, and exports/backups never enter the source tree.

## Known limitations / deferred items

* PST/OST require `readpst`/`pypff` (absent ⇒ NOT_CONFIGURED).
* UMAP/HDBSCAN and WeasyPrint are optional/absent; PCA/SVD and
  LibreOffice/Chrome PDF are used instead.
* The loopback API has no auth/TLS (mono-user only).
* PostgreSQL/pgvector path is dead/optional and unexercised.
* `src/ui/modern_app.py` remains as a legacy secondary entrypoint.
* Inherited static debt (Ruff/mypy) in legacy modules is not fully retired; the
  active canonical runtime subset was cleaned where risk was low.
