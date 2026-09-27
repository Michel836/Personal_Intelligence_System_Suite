# Original README → Current Application Functional Gap Matrix

> Audit-only document (no product code changed). Historical product intent
> (README) vs. current implementation truth (code/tests/runtime). Sanitized:
> no private paths, filenames or content.
>
> Audited baseline: branch `feat/m001-validation-harness`, working tree incl.
> M010/M011/M012-A. The mission header referenced `63240bc`; the audited tree is
> three commits newer (M012-A). No push.

## Legend

Status: `IMPLEMENTED`, `IMPLEMENTED_AND_IMPROVED` (IAI), `PARTIAL`,
`PLANNED_NOT_IMPLEMENTED` (PNI), `LEGACY_OR_DEAD`, `SUPERSEDED`,
`NOT_APPLICABLE_MONO_USER` (NA), `OBSOLETE_TECHNICAL_CHOICE` (OTC),
`NEEDS_VERIFICATION` (NV).
Priority: P0–P3. Milestone: CURRENT, M012-B, M013, M014, M015, M016, M017,
M018, M019, M020, BACKLOG, DROP. Action: KEEP, IMPROVE, COMPLETE, IMPLEMENT,
REPLACE, DEPRECATE, DROP, VERIFY.

## README layers

- **Layer A — Original v1 / claimed current**: LITE/Smart/Full launchers,
  activity monitoring, SQLite, filename/content search, scanning with
  priorities, incremental updates, PDF/DOCX/ODF extraction, AI chat, semantic
  search, tags/favorites, Plotly/NetworkX visualizations, dashboard/onboarding,
  cloud sync, "48+ formats", local-first privacy.
- **Layer B — Target architecture**: PostgreSQL 15 + pgvector, FastAPI, Redis,
  Celery, MinIO, Alembic, spaCy/Stanza, CLIP/LLaVA, FAISS/HDBSCAN/BERTopic,
  Three.js/Sigma.js/D3.js, Docker.
- **Layer C — Future roadmap**: mobile, voice, secure web/remote, share links,
  notifications, fine-tuning, predictive search, smart folders, VR/AR, memory
  assistant, federated search, autonomous agents, plugins.

## Master gap matrix

### Launch / resource modes

| ID | README feature | Layer | Current module/path | UI surface | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | LITE mode (30MB, <1s, port 8510) | A | `src/core/launch_profile.py` + `src/launcher.py` | canonical app, core pages | IMPLEMENTED (M012-B2) | yes | yes | measured 0.87s / ~169MB peak (old 30MB/<1s partly obsolete) | P2 | M012-B | DONE |
| L2 | Smart Launcher (module selection, estimation) | A | `src/launcher.py` + provider router | canonical app, hardware-aware AUTO | IMPLEMENTED (M012-B2) | yes | yes | module picker replaced by capability flags/profiles | P2 | M012-B | DONE |
| L3 | Full Power launcher (port 8501) | A | `src/launcher.py` → `src/ui/app.py` | canonical app, all pages | IMPLEMENTED (M012-B2) | yes | yes | ports are defaults, not requirements | P2 | M012-B | DONE |
| L4 | Performance presets / resource estimation | A | `core/perf_config.py` + `ai/providers/router.py` | AI status | IAI | yes (M010/M012-A) | yes | README numbers superseded | P1 | CURRENT | KEEP |
| L5 | Real-time activity monitoring + floating badge | A | `ui/real_time_monitor.py`, `ui/activity_monitor.py` | sidebar + badge | IMPLEMENTED | UI smoke | partial | history persistence limited | P1 | CURRENT | KEEP |
| L6 | Modern interface + onboarding | A | `ui/modern_app.py`, `ui/onboarding.py` | modern app | IMPLEMENTED | UI smoke | no | second UI surface to maintain | P2 | M020 | KEEP |
| L7 | Background scan without UI blocking | A | `core/scan_service.py` | scanner page | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |

### Scan / lifecycle

| ID | README feature | Layer | Current module/path | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | Multi-threaded scanning | A | `scanner/{fast_engine,engine}.py` | IAI | yes | yes | measured optimum is single-thread (M010) | P0 | CURRENT | KEEP |
| S2 | Incremental updates | A | `core/database.save_files_batch` | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| S3 | Change detection (size/mtime) | A | `database.py` UPSERT CASE | IMPLEMENTED | yes (M010) | yes | — | P0 | CURRENT | KEEP |
| S4 | Rename/move identity | A | `_associate_renames` + `core/volume.py` | IMPLEMENTED | yes | yes | — | P0 | CURRENT | KEEP |
| S5 | MISSING lifecycle / restore | A | `_mark_missing`, state column | IMPLEMENTED | yes | yes | — | P0 | CURRENT | KEEP |
| S6 | Configurable scan limits | A | `ScanRequest.limit` | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| S7 | Priority queuing (legal docs first) | A | `scanner/models.py` priority | PARTIAL | partial | no | not surfaced as a policy | P2 | M016 | IMPROVE |
| S8 | Multi-volume / mount handling | B | `core/volume.py` | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| S9 | Progress tracking (files/s) | A | `ScanProgress`, callbacks | IMPLEMENTED | partial | yes | — | P1 | CURRENT | KEEP |

### Search

| ID | README feature | Layer | Current module | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | Filename search | A | `database.search_files` FTS | IMPLEMENTED | yes | yes | — | P0 | CURRENT | KEEP |
| Q2 | Path search | A | `search_files` | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| Q3 | Content search (FTS5) | A | FTS triggers | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| Q4 | Semantic search | A/B | `semantic_search.py` + store | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| Q5 | Filters (type/ext/size/date) | A | `_build_filter_conditions`, `search/advanced_search.py` | IMPLEMENTED | yes | partial | UI coverage uneven | P1 | CURRENT | KEEP |
| Q6 | Sorting/relevance | A | FTS bm25 + ORDER BY | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| Q7 | Search suggestions | A | `advanced_search.suggest_searches` | PARTIAL | no | no | not wired in UI | P2 | M014 | IMPROVE |
| Q8 | Open file location | A | `open_file_location` | IMPLEMENTED | no | partial | Windows-first; Linux fallback partial | P1 | CURRENT | IMPROVE |
| Q9 | Open folder | A | same | IMPLEMENTED | no | partial | same | P1 | CURRENT | IMPROVE |
| Q10 | Legal-specialized search | A | `search/legal_search.py` | PARTIAL | no | no | not exposed as a page | P2 | M016 | IMPROVE |
| Q11 | Hybrid search (semantic+text) | B | `semantic_search.hybrid_search` | IMPLEMENTED | partial | partial | not surfaced | P2 | M014 | IMPROVE |

### Extraction

| ID | README feature | Layer | Current module | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| X1 | TXT/MD/CSV/JSON/HTML/XML/YAML/code | A | `text_extractor`, `enhanced_extractor` | IMPLEMENTED | yes | yes | — | P0 | CURRENT | KEEP |
| X2 | PDF | A | `pdf_extractor` | IMPLEMENTED | yes | yes | — | P0 | CURRENT | KEEP |
| X3 | DOCX/DOC/XLSX/XLS/PPTX/PPT | A | `office_extractor` | IMPLEMENTED | yes | yes | limited fidelity on legacy `.doc/.xls/.ppt` | P1 | CURRENT | IMPROVE |
| X4 | ODT/ODS/ODP | A | `odf_extractor`, `enhanced_extractor` | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| X5 | RTF | A | `enhanced_extractor` | PARTIAL | partial | no | unreliable | P2 | M017 | COMPLETE |
| X6 | Images + OCR | A | `ocr.py` | IMPLEMENTED (opt-in `PIS_OCR_ENABLED`) | yes | partial | disabled by default; CPU/GPU cost | P1 | M017 | IMPROVE |
| X7 | Email `.eml`/`.msg` | A | `enhanced_extractor` | PARTIAL | partial | no | attachments/metadata shallow | P1 | M017 | COMPLETE |
| X8 | PST/OST | A | — | PNI | no | no | deps commented out | P1 | M017 | IMPLEMENT |
| X9 | WordPerfect / legacy office | C | — | PNI | no | no | very low value now | P3 | BACKLOG | DROP |
| X10 | Archives + nested | B | `archives/*` | IAI | yes | yes | — | P1 | CURRENT | KEEP |
| X11 | Corrupt/encrypted/oversized archives | B | `archives/limits.py`, statuses | IAI | yes | yes | — | P1 | CURRENT | KEEP |
| X12 | Oversized file handling | A | `scanner/models.py` limits | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| X13 | Error/review queue for bad files | A | `extraction_state` | PARTIAL | partial | no | no UI queue | P2 | M017 | IMPROVE |
| X14 | "48+ formats" | A | union of extractors (~50 ext) | IMPLEMENTED | yes | partial | claim roughly holds | P2 | CURRENT | KEEP |

### Intelligence

| ID | README feature | Layer | Current module | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Embeddings | A/B | `embeddings.py`, `embedding_store.py` | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| A2 | Semantic search | A/B | `semantic_search.py` | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| A3 | RAG / AI chat | A | `chat_engine.py` + providers | IAI | yes | yes | — | P0 | CURRENT | KEEP |
| A4 | Summaries | A | `ai/advanced_ai.py` | IMPLEMENTED | partial | partial | LLM-dependent, no batch UI polish | P1 | CURRENT | IMPROVE |
| A5 | Document Q&A / history | C | `advanced_ai.ask_question` + `qa_history` | IMPLEMENTED | partial | partial | basic retrieval, no rerank | P2 | M014 | IMPROVE |
| A6 | Language detection | B | — | PNI | no | no | `langdetect` in requirements only | P2 | M015 | IMPLEMENT |
| A7 | Categorization / auto-classification | A | `ui/intelligence.generate_auto_tags` | PARTIAL | no | no | heuristic, not persisted classes | P2 | M015 | COMPLETE |
| A8 | Entity extraction (spaCy) | B | `core/models.Entity` (unused) | PNI | no | no | model exists, no NLP pipeline | P2 | M015 | IMPLEMENT |
| A9 | Duplicate detection (exact) | B | `dedup.exact.ExactDuplicateEngine` (SHA-256 `content_hashes`) | IMPLEMENTED (M014) | yes | yes | size-first incremental hashing; 72,268 groups / 57.9 GB on 303k corpus | P1 | M014 | DONE |
| A10 | Near-duplicate (MinHash/pgvector) | B | `dedup.near.NearDuplicateEngine` (hyperplane LSH + semantic confirm) | IMPLEMENTED (M014) | yes | yes | bounded, no O(N²); pgvector still an option >100k | P2 | M014 | DONE |
| A11 | Version tracking | B | `dedup.versions.VersionTracker` (`version_families`) | IMPLEMENTED (M014) | yes | yes | explicit-marker confidence; chronology never invented | P2 | M014 | DONE |
| A12 | Relationship mapping | B | `dedup.related.RelatedDocuments` (+ exact/near/version markers) | IMPLEMENTED (M014) | yes | yes | suggestions only, no destructive grouping | P2 | M014 | DONE |
| A13 | Clustering (HDBSCAN/K-means) | B | — | PNI | no | no | dep declared only | P3 | M020 | IMPLEMENT |
| A14 | Topic modeling (BERTopic) | B | — | PNI | no | no | — | P3 | M020 | IMPLEMENT |
| A15 | Similar-document search | A | `dedup.related.RelatedDocuments` + `semantic_search.find_similar_documents` | IMPLEMENTED (M014) | yes | yes | related panel in Duplicates page | P2 | M014 | DONE |
| A16 | Vision (CLIP/LLaVA) | B/C | — | PNI | no | no | `llava` config placeholder | P3 | BACKLOG | IMPLEMENT |
| A17 | Reranking (cross-encoder) | B | `dedup.rerank` (RRF fusion + exact-match boost) | IMPLEMENTED (M014) | yes | yes | transparent RRF; lexical fallback preserved | P2 | M014 | DONE |
| A18 | Agentic behavior | C | — (MCP tools only) | PNI | no | no | — | P3 | BACKLOG | DROP |
| A19 | MCP server | B | `mcp_server.py` | IMPLEMENTED | yes | partial | 3 read-only tools | P2 | CURRENT | KEEP |
| A20 | Contextual intelligence / recommendations | A | `ui/intelligence.py` | PARTIAL | no | no | heuristic; not wired to a page | P2 | M020 | IMPROVE |

### Visualization / UX

| ID | README feature | Layer | Current module | Status | Tests | Real-data | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| V1 | Dashboard | A | `ui/dashboard.py`, `analytics/dashboard.py` | IMPLEMENTED | UI smoke | yes | — | P1 | CURRENT | KEEP |
| V2 | Statistics | A | `statistics_page` | IMPLEMENTED | UI smoke | yes | — | P1 | CURRENT | KEEP |
| V3 | Charts (Plotly) | A | `visualizations/advanced_viz.py` | IMPLEMENTED | partial | yes | — | P1 | CURRENT | KEEP |
| V4 | Timeline | B | `analytics.get_timeline_stats`, viz temporal flow | IMPLEMENTED | partial | partial | basic | P2 | M016 | IMPROVE |
| V5 | Network graph | B | `advanced_viz.create_document_network_graph` | IMPLEMENTED | partial | partial | NetworkX, not Sigma.js | P2 | M016 | IMPROVE |
| V6 | 3D galaxy | B/C | `advanced_viz.create_file_universe_3d` | PARTIAL | no | no | Plotly 3D, not Three.js galaxy | P3 | M020 | IMPROVE |
| V7 | Advanced visualization suite | B | `advanced_viz` (7 views) | IMPLEMENTED | partial | partial | — | P2 | CURRENT | KEEP |
| V8 | Activity monitor + floating badge | A | `real_time_monitor` | IMPLEMENTED | UI smoke | partial | — | P1 | CURRENT | KEEP |
| V9 | Progress bars | A | scanner + UI | IMPLEMENTED | UI smoke | yes | — | P1 | CURRENT | KEEP |
| V10 | History (activity/QA/sync) | B | monitors + `qa_history` + `sync_history` | PARTIAL | partial | partial | fragmented | P2 | M014 | IMPROVE |
| V11 | Memory/CPU display | A | `core/monitoring.py`, activity monitor | PARTIAL | no | partial | MetricsCollector not fully wired | P2 | CURRENT | IMPROVE |
| V12 | File viewer | A | `file_viewer_page` | IMPLEMENTED | UI smoke | yes | — | P1 | CURRENT | KEEP |
| V13 | Archive-aware viewer | B | `archives/viewer.py` + UI | IMPLEMENTED | yes | yes | — | P1 | CURRENT | KEEP |
| V14 | Tags | A | `tags/tag_manager.py` | IMPLEMENTED | partial | partial | — | P1 | CURRENT | KEEP |
| V15 | Favorites | A | `tag_manager` favorites | IMPLEMENTED | partial | partial | — | P1 | CURRENT | KEEP |
| V16 | Reports | B | `analytics.export_stats` (JSON) | PARTIAL | partial | partial | no PDF | P2 | M018 | COMPLETE |
| V17 | PDF report export | B | — | PNI | no | no | — | P2 | M018 | IMPLEMENT |
| V18 | Dossier reconstruction | C | — | PNI | no | no | — | P3 | M018 | IMPLEMENT |

### Privacy / security

| ID | README feature | Layer | Current module | Status | Tests | Real-data | Mono-user | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | Local-first processing | A | canonical SQLite + local AI | IAI | yes | yes | KEEP | P0 | CURRENT | KEEP |
| P2 | No telemetry | A | none present | IMPLEMENTED | implicit | yes | PROTECT | P0 | CURRENT | KEEP |
| P3 | No automatic cloud | A | `cloud/sync_manager.py` (manual Dropbox) | IMPLEMENTED | partial | no | KEEP | P0 | CURRENT | KEEP |
| P4 | Remote-content policy | B | `ai/providers/policy.py` (M012-A) | IMPLEMENTED | yes | partial | KEEP | P1 | M012-B | KEEP |
| P5 | Sensitive-data/PII detection | B | — | PNI | no | no | IMPLEMENT | P2 | M015 | IMPLEMENT |
| P6 | Encryption at rest | B | config placeholder only | PNI | no | no | OPTIONAL | P2 | M015 | IMPLEMENT |
| P7 | Audit trail | B | `core/advanced_logging.py` + sync history | PARTIAL | no | no | IMPROVE | P2 | M015 | IMPROVE |
| P8 | Role-based access control | C | — | NA | — | — | DROP | P3 | DROP | DROP |
| P9 | Multi-user auth (JWT) | C | config placeholder | NA | — | — | DROP | P3 | DROP | DROP |

### API / CLI / automation

| ID | README feature | Layer | Current module | Status | Tests | Gap | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|---|---|
| I1 | FastAPI REST | B | — | PNI | no | README self-notes "not implemented" | P2 | M019 | IMPLEMENT |
| I2 | WebSockets | B | — | PNI | no | — | P3 | M019 | OPTIONAL |
| I3 | CLI (`36tb-intel`) | B | — | PNI | no | README self-notes "not implemented" | P2 | M019 | IMPLEMENT |
| I4 | Scripts (scan/extract/index/maintenance) | A | `scripts/*` | IMPLEMENTED (ad hoc) | partial | duplicated helpers | P1 | CURRENT | IMPROVE |
| I5 | MCP | B | `mcp_server.py` | IMPLEMENTED | yes | read-only only | P1 | CURRENT | KEEP |
| I6 | Automation/scheduling | C | — | PNI | no | — | P3 | M019 | OPTIONAL |
| I7 | Backup/restore/export | A | `cloud/sync_manager.py` | IMPLEMENTED | partial | Dropbox-centric | P1 | CURRENT | IMPROVE |
| I8 | Maintenance (optimize/clean) | B | scripts + Postgres vacuum | PARTIAL | no | SQLite VACUUM/optimize not exposed | P2 | M019 | COMPLETE |

### Data / storage / performance

| ID | README item | Layer | Current | Status | Priority | Milestone | Action |
|---|---|---|---|---|---|---|---|
| D1 | PostgreSQL 15 + pgvector | B | `core/postgres_database.py` (non-canonical) | OTC (optional scale backend) | P2 | M013/M019 | OPTIONAL |
| D2 | SQLite + FTS5 | A | `core/database.py` | IAI | P0 | CURRENT | KEEP |
| D3 | Embedding matrix store | B | `intelligence/embedding_store.py` | IAI | P0 | CURRENT | KEEP |
| D4 | Redis | B | — | OTC | P3 | DROP | DROP |
| D5 | Celery | B | — | OTC | P3 | DROP | DROP |
| D6 | MinIO | B | — | OTC | P3 | DROP | DROP |
| D7 | Alembic migrations | B | `alembic/` (Postgres path only) | PARTIAL | P2 | M019 | OPTIONAL |
| D8 | Docker/Dockerfile/compose | B | — | PNI | P3 | BACKLOG | OPTIONAL |
| Perf1 | 1,000 files/s scan | A | measured 9,604 files/s (M010) | IMPROVED | P0 | CURRENT | KEEP |
| Perf2 | Search <200 ms | A | FTS p50 0.5 ms/p95 28 ms; semantic ~0.05 ms | IMPROVED | P0 | CURRENT | KEEP |
| Perf3 | Startup <1 s / ~25 s | A | measured LITE/SMART/FULL app ready p50 0.87-0.88 s (M012-B2) | VALIDATED | P2 | M012-B | DONE |
| Perf4 | RAM 30 MB / 2.8 GB | A | at-rest canonical app ~169 MB peak, 0 MB VRAM; models load only on demand | REVISED | P2 | M012-B | DONE |
| Perf5 | 10M-doc search latency | B | projections only | NV | P1 | M013 | VERIFY |
| Perf6 | Embedding 200 docs/s | A | measured 14.7 vec/s (bge-m3, long docs) | OBSOLETE | P2 | M013 | REVISE |

## Protected functional contracts

Never regress: local-only operation & privacy; filename/content FTS search
without AI; fast scan + incremental/rename/MISSING lifecycle; direct
file/folder access; activity monitoring; offline operation; archive safety
limits; DB integrity/reconciliation; embedding store provenance isolation.

## Mono-user exclusions

RBAC/roles, family/guest access, multi-user auth/JWT, shared tenancy, per-user
audit identity. Retain encryption, local audit history, privacy controls,
backup, API/CLI, and remote access as mono-user-valuable.

## Dependency graph (drives milestone order)

```
extraction ──> language detection ──> entity extraction ──> categorization
                                                   └──> relationship mapping ──> timeline ──> graph
                                                                     └──> dossier reconstruction ──> reports/PDF
provider abstraction (M012-A) ──> hybrid/API validation (M012-B) ──> vision ──> advanced RAG ──> optional remote API/CLI

duplicates/versioning/related-docs (M014) depend on extraction + semantic search
reranking depends on semantic search + provider abstraction
```

## Proposed milestone roadmap

- **M012-B** (next): verify LITE/SMART/FULL launchers against the provider
  router; verify startup/RAM claims; optional real hybrid/API validation.
- **M013**: 250k–500k real-corpus scale; verify search/embedding projections.
- **M014**: duplicates, near-duplicates, versioning, related docs, reranking,
  unified history/similar-docs surfaces.
- **M015**: language detection, entity extraction, categorization, PII
  detection, encryption-at-rest, audit trail.
- **M016**: timeline, relationship graph, prioritization policy.
- **M017**: PST/email, legacy office, OCR hardening, extraction error queue.
- **M018**: reports/PDF export, dossier reconstruction.
- **M019**: opt-in local REST/CLI, maintenance/backup consolidation, optional
  Postgres/pgvector scale backend.
- **M020**: advanced visualization (galaxy), clustering/topic modeling,
  contextual intelligence surface.

## Top 10 highest-value missing mono-user capabilities

1. Duplicate/near-duplicate detection on the canonical SQLite path (M014).
2. Version tracking persisted (M014).
3. Related-documents + reranking for RAG quality (M014).
4. Language detection (FR/DE/EN) for search & routing (M015).
5. Entity extraction + categorization (spaCy) (M015).
6. PII/sensitive-content detection (M015).
7. PST/email extraction (M017).
8. Extraction error/review queue (M017).
9. PDF report/dossier export (M018).
10. Opt-in local REST/CLI + MCP parity (M019).

## Explicitly deferred / dropped

- Deferred: remote web/mobile/voice, share links, notifications, federated
  search, plugins, VR/AR (Layer C, no current dependency).
- Dropped: Redis, Celery, MinIO as core deps; multi-user RBAC/auth; WordPerfect;
  autonomous agents; hard MySQL/Postgres core dependency.
- Optional/scale-only: PostgreSQL + pgvector, Alembic, Docker.
