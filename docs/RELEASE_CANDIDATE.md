# Release Candidate — Install, Operate and Limits (M021)

This is the operator guide for the **v1.0.0-rc1** release candidate of 36TB
Intelligence. It describes the canonical path only: one Streamlit app, one CLI
(`pis`), one loopback API and one SQLite database.

> Feature freeze (M021). No new user capability is added here; this lot validates
> and stabilises M013–M020.

## 1. Install

Prerequisites: Python 3.11+, Linux/macOS/Windows, ~1 GB for the app + SQLite.

```bash
python -m venv .venv
source .venv/bin/activate           # .venv\Scripts\activate on Windows
pip install -r requirements.txt     # minimal: -r requirements-minimal.txt
```

Optional system tools (detected, never required): `tesseract` (OCR),
`libreoffice`/`soffice` (legacy Office/RTF and HTML→PDF export), `7z` (CHM),
`ollama` (local LLM/embeddings), `google-chrome`/`chromium` (alternate PDF).

## 2. Start / quick start

```bash
# Canonical app, three profiles
scripts/run_lite.sh     # fastest, lowest resources, local-only AI
scripts/run_smart.sh    # hardware-aware AUTO, all capabilities lazy
scripts/run_full.sh     # every implemented capability, lazy-loaded

# Equivalent unified launcher
.venv/bin/python -m src.launcher --profile full --port 8501
.venv/bin/python -m src.cli ui full
```

First run: scan a root, extract, then search.

```bash
pis scan /path/to/corpus
pis extract --limit 500
pis semantic-refresh --limit 256      # optional; needs an embedding backend
pis search "invoice" --mode lexical
pis ui full
```

The resolved database path is always printed, so a trial and a production target
cannot be confused. An explicit `--db PATH` selects another database.

## 3. Daily workflow

1. **Scan** the corpus (`pis scan` or the Scanner page) — incremental, no-change
   scans are cheap and never rewrite sources.
2. **Extract** content (`pis extract`) — bounded, retried, with an error queue.
3. **Understand** (`pis intel`) — language, entities, categories, PII.
4. **Find** — lexical FTS, semantic, reranked search.
5. **Relate** — duplicates, versions, related docs, timeline, graph.
6. **Decide** — dossiers and reports (HTML/JSON/PDF) with citations.
7. **Explore** — Galaxy & Topics (clusters, topics, contextual view).
8. **Maintain** — Operations page / `pis doctor`, `pis maintenance`, backups.

## 4. Profile differences

| | LITE | SMART | FULL |
|---|---|---|---|
| Core pages (scan/search/viewer/duplicates/intel/graph/ingest/reports/ops) | ✓ | ✓ | ✓ |
| Advanced pages (AI chat, semantic, visualizations, galaxy, auto-extract, cloud) | — | ✓ | ✓ |
| AI mode | `local` | `auto` | `auto` |
| Heavy preload | off | off | off |
| `PIS_REMOTE_CONTENT_POLICY` | `never` | `never` | `never` |
| Preferred port | 8510 | 8504 | 8501 |

A profile never relaxes privacy and never preloads a heavy model. Advanced
capabilities can still be toggled with `PIS_FEATURE_<NAME>=0/1`.

## 5. Data and privacy model

* **SQLite is canonical** (`data/indexes/files.db`, override with `PIS_DB_PATH`).
  PostgreSQL/pgvector is optional and was measured **unavailable** — the NumPy
  matrix store remains the vector backend.
* **Local-only by default.** `PIS_REMOTE_CONTENT_POLICY=never` is authoritative
  and cannot be relaxed by a profile. Remote sending requires an explicit policy
  (`metadata_only` < `extracted_text` < `full_context`) plus an explicitly
  configured API backend and key.
* **PII is masked** in the API and in reports under `MASK_PII`; the store keeps
  only a masked display and a salted fingerprint, never raw values.
* **Source files are never modified by design**: the scanner is read-only,
  extraction uses temp space, and backups/restores/exports never write into the
  scanned tree.
* The HTTP API is **loopback-only and unauthenticated by design**; binding a
  non-loopback host is refused unless `--allow-remote` and carries no auth/TLS.

## 6. Backup / restore

```bash
pis backup --out /backups                 # WAL-safe SQLite snapshot + semantic store + redacted config
pis restore /backups/<archive> --verify-only
pis restore /backups/<archive> --target-db /restore/files.db --confirm --semantic
```

* Backups carry a **manifest** (schema, backup id, checksums, components, privacy
  note) and never include the source corpus.
* Restore is conservative: verify archive safety + checksums, check schema
  compatibility, stage, `integrity_check`, refuse to overwrite unless `--force`,
  keep a `.pre-restore` rollback copy.
* Derived galaxy/cluster/topic tables live in the database and are restored with
  it. The semantic matrix store is restored when `--semantic` is passed;
  otherwise it is **rebuilt** on the next refresh (verified in M021).

## 7. Troubleshooting

| Symptom | Action |
|---|---|
| Wrong database | Check the printed DB path; pass `--db`; `pis status`. |
| Port in use | The launcher auto-selects a free port; an explicit `--port` fails loudly. |
| Stale instance lock | The lock self-recovers when the owner PID is dead (`~/.pis-locks`). |
| Semantic unavailable | Run `pis semantic-refresh`; check `pis doctor`; missing model falls back to lexical. |
| GPU unavailable / CUDA OOM | The embedding path retries smaller batches and falls back to CPU; lexical search always works. |
| PDF export missing | Install `libreoffice`/`chrome`; HTML/JSON are always produced. |
| OCR needed | `PIS_OCR_ENABLED=1` and install `tesseract`. |
| PST/OST | Requires `readpst` (libpff-tools) or `pypff`; absent ⇒ reported NOT_CONFIGURED. |
| Disk full | `pis doctor` reports free space; maintenance `vacuum` has a free-space precheck. |

## 8. Optional dependencies and format matrix

`pis intel`/`pis doctor` and the capability matrix report the live status. Current
environment: PDF (PyPDF2), DOCX/XLSX (python-docx/openpyxl), ODT (odfpy), EML,
EPUB (stdlib), ZIP/7z archives, RTF (libreoffice) are available; **PPTX**
(python-pptx), **MSG** (native CFB is partial), **PST/OST** (readpst/pypff),
**UMAP/HDBSCAN**, OCR (tesseract enabled=off by default) and WeasyPrint are not.

Statuses: SUPPORTED · PARTIAL · OPTIONAL_DEPENDENCY_MISSING · DEFERRED ·
UNSUPPORTED. An unsupported/malformed/encrypted file is recorded once with an
actionable outcome and is never retried forever.

## 9. Scale envelope (measured)

* 80 039-vector corpus: PCA projection 6.6 s, MiniBatchKMeans 4.5 s, topics 3.3 s,
  peak service RSS ~2.0 GB (OS peak 5.1 GB with the 570 MB matrix), status FRESH.
* Galaxy UI: figure build ≤ 0.13 s and payload < 1 MB at the default point limits
  (SMALL 6k / MEDIUM 8k / LARGE aggregate).
* Maintenance: integrity check ~11 s, SQLite backup ~198 s for a 1.5 GB archive
  (trial copy, M019). Restore verified with matching counts.

## 10. Known limitations

* UMAP/HDBSCAN are not installed; only PCA/SVD are available.
* Optional local-LLM topic refinement is defined but not enabled.
* Cluster ids are run-scoped (no cross-rebuild stability guarantee).
* Remote API has no auth/TLS (loopback, mono-user only).
* PostgreSQL/pgvector path is dead/optional and not exercised.
* `modern_app.py` is a legacy second entrypoint; the canonical app is
  `src/ui/app.py`.

## 11. Canonical vs stale surface

| Workflow | Canonical | Stale / legacy (kept, unwired or clearly secondary) |
|---|---|---|
| App | `src/ui/app.py` (+ profile launcher) | `src/ui/modern_app.py` |
| Scan | `scanner/fast_engine.py` via `ScanService` | `scanner/engine.py`, `scanner/turbo_scan.py` |
| Visualisation | `ui/galaxy_page.py`, `ui/graph_page.py` | `visualizations/advanced_viz.py` 3D scatter (non-semantic) |
| Vector backend | NumPy matrix store | `core/postgres_database.py` (dead) |
| CLI/API | `src/cli.py`, `src/api/` | historical `scripts/*` helpers |

## 12. Release acceptance evidence

* `tests/release/` — 38 deterministic acceptance tests (E2E, lifecycle/crash,
  profiles, backup round-trip, privacy, CLI/API, UI smoke).
* `scripts/release/run_release_acceptance.py` — aggregate acceptance evidence
  (timings + counts) under `/home/chu/.pis-trials/m021/evidence/`.
* `.validation/<UTC>/validation.json` — audit/compileall/pytest/diff-check gates.
* `/home/chu/.pis-trials/m020/evidence/` — M020 real-corpus benchmark.
* Full suite: **747 passed, 5 intentional skips** (see release notes).
