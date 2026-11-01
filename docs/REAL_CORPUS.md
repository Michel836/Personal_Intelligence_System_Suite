# Real-Corpus MVP Run — Instrumented Evidence (M022)

> **Sanitised evidence.** This document records aggregate counts, timings and
> root *categories* only. It contains no filenames, no full paths, no document
> content and no personal data. Raw evidence stays outside the repository in
> `~/.pis-trials/<timestamp>/`.

**Date:** 2026-11-01 (UTC)
**Branch:** `chore/dual-license-agpl-commercial` (working tree incl. M022)
**Profile:** FULL (local embeddings, `PIS_REMOTE_CONTENT_POLICY=never`)
**Host:** Linux 7.0.0, Intel i9-14900 (32 threads), 62 GB RAM,
NVIDIA RTX 3090 24 GB, Python 3.11.15
**Embedding model:** `all-MiniLM-L6-v2` (384 dims, fp16 on CUDA)
**Trial data dir:** `~/.pis-trials/mvp-20261101T181116/data`
**Trial DB:** `~/.pis-trials/mvp-20261101T181116/data/indexes/files.db`

This is the end-to-end run requested for the MVP gate: **scan → extract all
documents → intelligence → duplicates → incremental embeddings → clusters /
galaxy → reports**, on real user files, with no source file modified.

---

## 1. Corpus

Three real root categories were scanned into a single trial database:

| Root category | Files indexed | Wall time |
|---|---:|---:|
| Documents | 821 | 0.22 s |
| Calibre Library | 47 | 0.18 s |
| Downloads | 14 324 | 0.63 s |
| **Total** | **15 192** | **~1.0 s** |

The scanner's canonical exclusion policy was active (hidden files, VCS/cache/
build directories, OS binaries, symlinks). The corpus is a real mixed personal
corpus: PDFs, Office/ODF documents, text/markdown, code, and archives.

`pis scan` finished **COMPLETED** on every root with **0 access errors** and
**0 unscanned scopes**; the new safe-partial mode was therefore not needed for
this corpus (it is covered by `tests/integration/test_scan_partial_contract.py`).

---

## 2. Pipeline results

| Step | Command | Wall time | Throughput / result |
|---|---|---:|---|
| Scan | `pis scan <root>` × 3 | 1.03 s | 15 192 files indexed (~14.7k files/s) |
| Extraction | `pis extract --limit 500` × 3 | 37 s | 661 attempted, **620 extracted** (16.8 docs/s) |
| Intelligence | `pis intel --limit 500` × 3 | 14 s | 615 docs processed (43.9 docs/s) |
| Exact hashes | `pis hashes --max-size 50MiB` | 1.5 s | 2 609 files hashed, 1.16 GB read, **1 019 duplicate groups** |
| Near duplicates | `pis hashes --near --limit 5000` | 30.1 s | **4 588 near-duplicate edges**, 1 064 total groups |
| Embeddings | `pis embed` (all pending) | 8.3 s | **614 / 614 eligible docs = 100 %**, 73.9 docs/s |
| Clusters / topics | `pis clusters --build --k 12` | 2.0 s | **12 clusters** with c-TF-IDF topics |
| Galaxy | `pis galaxy --limit 1000` | < 1 s | 614 points, 16 clusters (projection not persisted) |
| Reports | `pis report build` × 2 | < 1 s | 2 definitions, **5 artifacts** (HTML/JSON/PDF) |
| Status | `pis status` | — | `semantic=100.0% (614/614)`, queue=41 |

### Extraction outcomes (canonical taxonomy)

| Outcome | Count |
|---|---:|
| `EXTRACTED` | 620 |
| `NO_TEXT` | 29 |
| `PERMANENT_ERROR` | 11 |
| `ENCRYPTED` | 1 |
| **Attempted** | **661** |

The 41 non-extracted documents are recorded in the bounded extraction queue
(terminal; no retry loop). Nothing was silently dropped.

---

## 3. Derived intelligence (aggregate)

### Language detection (615 documents)

| Language | Documents |
|---|---:|
| code | 295 |
| fr | 229 |
| en | 72 |
| es | 6 |
| de | 4 |
| nl | 3 |
| pt | 3 |
| und | 2 |

### Entities (top types)

| Type | Extractions |
|---|---:|
| DATE | 3 791 |
| URL | 919 |
| PHONE | 418 |
| ORGANIZATION | 356 |
| MONEY | 285 |
| LOCATION | 273 |
| EMAIL | 133 |
| PERSON | 105 |

### Categories

`technology` 24 · `finance` 4 · `media` 4 · `administration` 1 ·
`education` 1 · `personal` 1 · `work_career` 1.

### PII (masked only; no raw values stored)

**1 138 findings across 148 documents**: phone 418 · postal address 361 ·
email 133 · person name 105 · IP 64 · account id 22 · card 10 · IBAN 9.

### Duplicates / versions

| Metric | Value |
|---|---:|
| Files with an exact SHA-256 hash | 2 727 |
| Exact duplicate groups | 1 064 |
| Near-duplicate edges | 4 588 |
| Version families | **0** |

No version family was inferred because this corpus does not contain explicit
version markers (the tracker never invents chronology).

### Semantic / galaxy

| Metric | Value |
|---|---:|
| Eligible documents (content > 50 chars, ACTIVE) | 614 |
| Embedded vectors | 614 |
| Coverage | **100.0 %** |
| Dirty rows at end | 6 (below embedding threshold) |
| Matrix store size | 1.9 MB (`matrix.npy`) |
| Cluster runs | 1 |
| Cluster members | 614 |
| Topics | 12 |

### Storage

| Artefact | Size |
|---|---:|
| SQLite database | 71.1 MB |
| Embedding store | 1.0 MB |
| Whole trial data directory | 69 MB |

---

## 4. Reproducible command sequence

```bash
TRIAL="$HOME/.pis-trials/mvp-$(date +%Y%m%dT%H%M%S)"
export PIS_DATA_DIR="$TRIAL/data"
export PIS_EMBEDDING_STORE_DIR="$TRIAL/data/cache/embeddings"
export PIS_EXPORT_DIR="$TRIAL/exports"
export PIS_NO_AUTO_MIGRATE=1
unset PIS_DB_PATH

# 1. Scan (safe-partial is the default; --strict opts into fail-closed)
for root in "$HOME/Documents" "$HOME/Calibre Library" "$HOME/Downloads"; do
  pis scan "$root"
done

# 2. Extract every eligible document (bounded batches of 500)
while pis extract --limit 500 | grep -qv 'attempted=0'; do :; done

# 3. Intelligence, duplicates, embeddings
pis intel --limit 500        # repeat while processed>0
pis hashes --max-size 52428800
pis embed                    # resumable; --background for long runs
pis hashes --near --limit 5000

# 4. Derived views and reports
pis clusters --build --k 12
pis galaxy --limit 1000
pis report build --kind SEARCH --query '{"query":"facture"}' --formats HTML,JSON,PDF
pis report build --kind DUPLICATES --formats HTML,JSON

# 5. Verification
pis status
pis embed --status
pis maintenance semantic-consistency
pis doctor
```

---

## 4b. Legacy database reconciliation (operational check)

The migration of an existing pre-XDG database (1 757 575 indexed files, 2.5 GB)
was exercised on the operator host:

1. `pis migrate-data` moved `./data` to `~/.local/share/pis` (182 files,
   2.55 GB) and bound the database to the migrated vector store;
2. `pis embed --rebuild` re-embedded the tracked corpus to repair a legacy
   store/DB mismatch: **8 384 docs in 37.4 s (224 docs/s)**;
3. `pis maintenance semantic-consistency` → **OK**, `store_vectors = 8 384`,
   `embedded_rows = 8 384`, `store_checked = true`;
4. `pis status` from an unrelated working directory resolves the same database
   (`~/.local/share/pis/indexes/files.db`), proving CWD independence.

This validates the migration path and the repair/rebuild command on a
million-file database, not only on the 15k-file trial corpus.

## 5. What this run validates

* The canonical **scan → extract → search → intelligence → duplicates →
  embeddings → clusters → reports** loop works end-to-end on real files.
* **Semantic coverage is measurable and complete** for eligible documents, with
  a resumable job (`pis embed --status` reports 100 %).
* **Reconciliation stayed safe**: 15 192 ACTIVE files, 0 MISSING, 0 access
  errors; no source file was modified.
* **Privacy**: PII is stored masked/fingerprinted only; the remote-content
  policy stayed `never`; no network content call occurred.
* The semantic store is **self-contained under `PIS_DATA_DIR`** and
  `maintenance semantic-consistency` checks the store bound to the database
  (`store_vectors == embedded_rows`, `store_checked=true`).

## 6. What this run does **not** validate

* **Scale beyond ~15k files / 614 embedded documents.** The 36 TB / multi-
  million-document promise still needs a dedicated, budgeted run (M013-B).
  Embedding throughput (≈74 docs/s with all-MiniLM on this GPU) means 1 M
  documents ≈ 3.8 h of GPU time; a background job is now available, but a
  full-corpus embedding policy (scope/priority) remains an operator choice.
* **Version families** (no version markers in this corpus).
* **Cloud sync, OCR-heavy corpora, PST/OST** (external tools / opt-in).
* **Windows/macOS packaging** (Linux-first MVP).
* **UI interaction**: the Streamlit pages are covered by `tests/ui/` and a
  headless smoke test, not by manual click-through in this run.

## 7. Interpretation

For this corpus the MVP is **functionally complete and operationally credible**:
a user can scan a real disk, extract, search lexically and semantically, inspect
duplicates, explore clusters, and export a report, with measurable coverage and
no data loss. The remaining distance to a *product* is distribution (clean
install, as validated by the wheel smoke test) and scale evidence, not missing
core functionality.
