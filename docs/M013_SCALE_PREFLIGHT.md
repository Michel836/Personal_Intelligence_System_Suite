# M013-A — Scale-Up Preflight (250k–500k)

**Status:** PREFLIGHT ONLY — no 250k–500k production scan was performed.
**Branch:** `feat/m001-validation-harness`
**Baseline HEAD:** `9c2a877`
**Trial root:** `/home/chu/.pis-trials/m013/`
**Source corpus:** READ ONLY. No source file was created, modified, renamed or deleted by this lot.

> This document is sanitised: it contains aggregate counts and selected **root
> directories** only. No individual filenames, private paths or per-file lists
> are recorded in the repository.

---

## A. Baseline

| Item | Value |
|---|---|
| HEAD | `9c2a8772552088bb63cc3cc4cd49436a8cea9545` |
| Branch | `feat/m001-validation-harness` |
| Tree at start | clean |
| Python | 3.11.15 (`.venv`) |
| SQLite | 3.46.1 |
| Streamlit | 1.64.0 |
| Torch | 2.14.0+cu130, CUDA available |
| CPU | Intel Core i9-14900, 24 physical / 32 logical |
| RAM | 62.6 GB usable |
| GPU | NVIDIA RTX 3090, 24 576 MiB VRAM, driver 595.91.07 |
| Free disk (repo / trial / cache = `/`) | 1.7 TB of 3.7 TB (52 % used) |
| Free disk `/tmp` (tmpfs) | 27 GB |
| Ollama | 0.34.0, daemon up, **no model loaded** (`ollama ps` empty) |
| Launch profiles | LITE/SMART/FULL from `src/core/launch_profile.py` |
| Default profile | FULL (direct start); `PIS_REMOTE_CONTENT_POLICY=never` in every profile |

Resolved resource defaults (`ResourceConfig`): scan=1, extract=1, archive=1,
OCR=8, db batch=1000, embedding batch=128, fp16=on, BLAS=16, bulk index=on,
`max_ram_gb`=37, `PIS_REMOTE_CONTENT_POLICY=never`.

Reference trial DB sizes (M010/M011): metadata DB after scan of 91 998 physical
files = **124.8 MiB**; after 17 620 archive-member rows = **155.3 MiB**;
embedding store for 440 vectors = **6.0 MiB**.

M010/M011 anchors used below: scan **9 603.7 files/s**; extraction **82.1 docs/s**
(496 smallest files); archive listing **167 archives/s** (3 439 mostly-rejected
archives); BGE-M3 embedding **14.7 vec/s** (fp16, batch 128, VRAM peak 23.9 GB);
semantic no-change sweep **O(1)** (~2 ms at 100k rows).

---

## B. Candidate roots

Measured with `scripts/bench/m013_preflight.py` (read-only, mirrors production
`FastScannerEngine` exclusions exactly — parity verified against M010 counts).

| Root | Eligible files | Eligible bytes | Canonical archives | Decision |
|---|---:|---:|---:|---|
| `/home/chu/Desktop` | 273 757 | 839.6 GB | 7 095 | **SELECTED** |
| `/home/chu/Projects` | 16 603 | 0.36 GB | 16 | **SELECTED** |
| `/home/chu/Téléchargements` | 12 035 | 158.1 GB | 6 | **SELECTED** |
| `/home/chu/Zotero` | 766 | 0.01 GB | 0 | **SELECTED** |
| `/home/chu/Documents` | 354 | 15.2 GB | 7 | **SELECTED** |
| `/home/chu/Calibre Library` | 47 | 0.01 GB | 0 | **SELECTED** |
| `/home/chu/Dropbox` | 1 947 | 1.46 GB | 5 | rejected (mirror) |
| `/home/chu/Android` (SDK) | 28 698 | 6.2 GB | 1 | rejected (vendor) |
| `/home/chu/Tools` | 4 088 | 38.5 GB | 0 | rejected (tooling) |
| `/home/chu/Applications` | 3 179 | 6.8 GB | 1 | rejected (app bundles) |
| `/home/chu/Sauvegardes` | 2 756 | 25.0 GB | 0 | rejected (backup/DB) |
| `/home/chu/LucasChessR` | 2 360 | 0.94 GB | 76 | rejected (app data) |
| `/run/media/.../Users` (external NTFS) | 189 446 | 698.3 GB | ~330 | rejected (system/AppData) |

Curated external subset measured but **deferred** (not in the corpus):
`…/Users/chume/{Documents,Desktop,Downloads,Pictures,OneDrive,Zotero,Music}`
≈ 17 710 eligible (798 PDFs, 300 canonical archives, 236 email-like). Kept out
to preserve a single-volume, no-external-mount corpus. Can be added for M013-C
if additional document diversity is desired.

---

## C. Exclusion policy

Exactly the production model (`src/scanner/fast_engine.py`), not a parallel one:

* **Directories (path component match, case-insensitive):** `windows`,
  `program files`, `program files (x86)`, `programdata`, `$recycle.bin`,
  `system volume information`, `windows.old`, `recovery`, `.git`, `.hg`, `.svn`,
  `.venv`, `venv`, `env`, `node_modules`, `__pycache__`, `.pytest_cache`,
  `.mypy_cache`, `.ruff_cache`, `.tox`, `.nox`, `dist`, `build`, `coverage`,
  `.coverage`, `.cache`; plus `\appdata\local\temp` (Windows).
* **Files:** hidden names (`.*`) and extensions `.dll .sys .exe .msi .tmp .log
  .cache .lock .pid .swp .~ .lnk .bak .temp`.
* **Metadata size:** `METADATA_INDEX_LIMIT = None` → every size is indexed.
  Hashing/extraction are separately capped at 50 MiB.
* **Symlinks:** `os.walk`/`scandir` never follow symlinked directories;
  symlinked files are counted separately and excluded from the *physical* tally.

`tests/unit/test_m013_preflight.py` asserts `SKIP_DIRS`/`SKIP_EXT` are **equal**
to `FastScannerEngine._skip_dirs`/`._skip_extensions` and that pruning is
component-based (e.g. `recovery_notes` is not pruned).

Aggregate exclusions across selected roots: **2 057** pruned directories,
**1 359** hidden files, **1 827** skip-extension files, **0** permission errors,
**0** special files.

---

## D. Discovery counts (selected set)

| Metric | Value |
|---|---:|
| Eligible physical files | **303 562** |
| Eligible bytes | 1 013.2 GB |
| Raw regular files (post-prune) | 306 788 |
| Raw bytes | 1 017.4 GB |
| Directories walked | 45 661 |
| Symlink files (not counted physical) | small (<100) |
| Special files | 0 |
| Permission errors | 0 |

Per-root eligible counts are in section B. `Documents` is intentionally small
because its large `.venv` subtree is correctly pruned (48 320 of its 48 674 raw
files).

---

## E. Format distribution (eligible, selected set)

Category histogram:

| Category | Files | Bytes |
|---|---:|---:|
| image | 98 888 | 19.0 GB |
| audio | 55 516 | 153.7 GB |
| text | 51 711 | 6.6 GB |
| code | 30 574 | 0.6 GB |
| extensionless | 23 142 | 9.4 GB |
| other | 17 345 | 128.6 GB |
| archive | 8 267 | 203.9 GB |
| video | 6 395 | 440.4 GB |
| binary | 5 280 | 10.7 GB |
| pdf | 4 209 | 33.8 GB |
| office | 1 948 | 1.0 GB |
| email | 195 | 0.1 GB |
| database | 92 | 5.6 GB |

Top extensions: `.jpg` 88 375 · `.mp3` 54 694 · *extensionless* 23 142 ·
`.json` 20 719 · `.py` 16 897 · `.xml` 12 265 · `.h` 10 214 · `.csv` 8 732 ·
`.png` 7 515 · `.zip` 6 896 · `.mp4` 5 633 · `.txt` 5 598 · `.pdf` 4 209 ·
`.docx` 1 301. Distinct extensions: **1 274**. Long tail (<100 files each):
≈ 1 100 extensions.

---

## F. Archive profile

Canonical archive extensions (the only ones the archive indexer understands):

| Format class | Files | Bytes |
|---|---:|---:|
| ZIP | 6 896 | 61.9 GB |
| RAR | 56 | 24.6 GB |
| TAR_GZ/TGZ | 35 | 3.1 GB |
| GZ | 110 | 0.11 GB |
| BZ2 / XZ / TAR_XZ / TAR | 27 | <0.7 GB |
| **Canonical total** | **7 124** | **90.3 GB** |

Non-indexed bundle/container extensions that merely look archive-like and are
**not** parsed: `.apk` 932 (57.6 GB), `.deb` 121, `.rpm` 42, `.iso` 18,
`.appimage` 10, `.wheel` 9, `.xapk` 5, `.zstd` 1, `.cab`/`.lz4` (external SSD).

**Bounded listing sample (281 canonical archives, no extraction):**
status `OK` 110, `NOT_ARCHIVE_FORMAT` 144, `LIMIT_MEMBER_SIZE` 24,
`CORRUPT_ARCHIVE` 2, `LIMIT_MEMBER_COUNT` 1; members created 6 659
(amplification 23.7 per sampled archive / 60.0 per usable archive); expanded
880 MB vs 505 MB compressed; **0 encrypted members**; one `.tar.gz` hit the
5 000-member cap (limits working). The very high `NOT_ARCHIVE_FORMAT` rate is
expected: most `.zip` files in the Android backup are proprietary files with a
misleading extension (M010 measured the same effect: 3 272 / 3 439).

Expected whole-corpus archive work: ≈ **2 500–3 000 usable archives**,
≈ **20 000–35 000 virtual member rows**, all inside the existing safety budget
(`max_depth=3`, `max_members=5000`, `max_member_bytes=64 MiB`,
`max_total_uncompressed=1 GiB`, `max_ratio=200`, `timeout=30 s`).

---

## G. Extraction profile estimate (measured × estimated)

Bounded stratified sample of **622** eligible files (mixing small and large):

| Outcome | Count | Share |
|---|---:|---:|
| success (text produced) | 493 | 79.3 % |
| no-text (e.g. image-only PDF) | 25 | 4.0 % |
| malformed (legacy `.doc`/`.xls`/`.ppt`) | 25 | 4.0 % |
| unsupported (image/audio/video/epub/rtf/eml) | 79 | 12.7 % |

Measured on this random sample: **13.7 docs/s**, peak RSS **384 MB**, 30.8 M
content characters from 869 MB input. *(The M010 anchor of 82 docs/s was
measured on the smallest files; random sampling is slower because of large
PDFs — the extractor caps them at 100 pages.)*

Extraction coverage is determined by the production extractors: PDF; DOCX/DOC,
XLSX/XLS, PPTX/PPT; ODT/ODS; and text (`txt log md csv json xml html htm py js
css sql yaml yml ini cfg bat sh ps1 msg`). Applying measured per-extension
success rates to the real histograms gives **≈ 70 800 content-bearing
documents** (95 % of them text/JSON/XML/CSV/PY, plus ≈ 2 760 PDFs and ≈ 1 500
Office/ODF).

OCR candidates (only if `PIS_OCR_ENABLED=1`): ~1 300 image-only PDFs
(sampled 31 % of PDFs) **plus 98 888 images** → unacceptable explosion; OCR
stays **OFF**.

Legacy formats: `.doc 6, .xls 12, .ppt 0` were malformed in the sample;
email: `.msg` extracts, `.eml` unsupported. Large documents (>50 MiB) are
metadata-only by policy.

---

## H. Selected corpus

**303 562 eligible physical files / 1 013.2 GB / 7 124 canonical archives**, in
this root order:

1. `/home/chu/Desktop`
2. `/home/chu/Projects`
3. `/home/chu/Téléchargements`
4. `/home/chu/Zotero`
5. `/home/chu/Documents`
6. `/home/chu/Calibre Library`

Rationale: single internal volume, no external-mount dependency; contains the
full M010 reference subtrees (comparability); strongest available mix of
archives, PDFs, Office, e-mail, text, code and images; well inside 250k–500k
and above the preferred 300k floor. Sanitised machine-readable manifest:
`docs/M013_CORPUS_MANIFEST.json`.

---

## I. Overlap / duplication analysis

* **Nested roots:** none (no selected root is inside another; `Projects` is not
  under `Desktop`).
* **Device identity:** all selected roots on `/dev/nvme0n1p2`; `mount_escape_files
  = 0`.
* **Exact path-tree mirrors:** one found — `Dropbox/Recherche_Emploi_*` shares
  **661** exact `(relpath,size)` entries with `Desktop/Recherche_Emploi_*`
  (Jaccard 0.47). Dropbox was therefore **excluded** from the corpus.
* **Content-signature sampling** (1 500 files/root, first 32 KiB + size):
  cross-root matches were ≤ 0.42 % of the smaller sample for every other pair —
  no other meaningful duplication.
* **Backup trees inside `Desktop`:** the `Sauvegarde_*` and `BackUp_*` subtrees
  are the *primary* corpus (they define the M010 set), not a second copy of a
  selected root.

Residual risk: `Desktop` contains an old `Calibre Bibliotheque`/`BinauralPlayer`
backup that partially echoes `Calibre Library`/`Documents`; effect < 0.02 % of
the corpus.

---

## J. Expected DB growth

Anchors: 1 422 B/physical row (incl. FTS + indexes, from M010 scan-only DB);
1 818 B/archive-member row; content stored as UTF-8 with an FTS5 index.

**M013-B (scan + lifecycle + FTS + archives, no content):**

| Component | Low | Expected | High |
|---|---:|---:|---:|
| SQLite metadata+FTS | 380 MB | 480 MB | 650 MB |
| WAL peak | 32 MB | 64 MB | 256 MB |

**M013-C (extraction + semantic + embeddings):**

| Component | Low | Expected | High |
|---|---:|---:|---:|
| Metadata DB (base + content + FTS) | 1.2 GB | 2.6 GB | 5.0 GB |
| `semantic_state` (~71k rows) | 5 MB | 9 MB | 15 MB |
| Embedding store (~71k × 4.1 KiB) | 210 MB | 290 MB | 600 MB |
| **Total growth** | **≈1.4 GB** | **≈2.9 GB** | **≈5.8 GB** |

These are projections, not guarantees; they use M010 bytes/row and a
chars-based content estimate with a wide band.

---

## K. Expected embedding workload

Content-bearing ratio from measured extractor coverage:
**0.233 vectors / eligible file**.

| Corpus size | Expected vectors |
|---|---:|
| 250 000 | ≈ 58 000 |
| **303 562 (selected)** | **≈ 70 800** |
| 500 000 | ≈ 116 600 |

* Selected target: **below 100k** → pgvector comparison **strongly recommended**
  but not mandatory.
* **500k scale crosses 100k → pgvector benchmark becomes REQUIRED for M013-C.**
* Hard ceiling remains 2 000 000 vectors.

---

## L. Resource capacity

| Resource | Assessment | Evidence |
|---|---|---|
| CPU | **GREEN** | 24C/32T; scan measured 88 % of one core; single-worker paths are I/O/GIL bound |
| RAM | **GREEN** | extraction peak 384 MB; embedding peak 2.1 GB; guard 8 GB / config 37 GB |
| VRAM | **AMBER** | BGE-M3 fp16 peaked at **23.9 / 24.0 GB** in M010 → must ensure no Ollama model is resident; batch fallback 128→64→32 |
| Disk | **GREEN** | 1.7 TB free vs ≤5.8 GB projected (>>2× margin) |
| SQLite | **GREEN** | single writer + bulk index + bounded WAL; integrity check planned |
| Archive volume | **AMBER-lite** | 7 124 canonical / 90.3 GB; limits already bound member explosions; watch `LIMIT_MEMBER_COUNT` |
| Semantic store | **GREEN** | ≈71k vectors, ~290 MB, O(1) no-change refresh |

---

## M. Throughput projection

| Stage | Measured anchor | Projection (303 562 files) | Uncertainty |
|---|---|---|---|
| Scan + FTS | 9 603.7 files/s (M010) | **≈ 32 s** (conservative 2 000 files/s → ~150 s) | cold cache/I-O |
| Archive index | 167/s mostly-reject; 10.8/s real-archive sample | **1–8 min** | archive validity mix |
| Extraction | 82 docs/s smallest; 13.7 docs/s random | **15–85 min** for ~71k docs | document size mix |
| Embedding | 14.7 vec/s | **≈ 80 min** for ~71k (≈113 min at 100k) | GPU availability |
| FTS validation | seconds | < 1 min | — |
| Reconcile | M010 fast | < 5 s (hard stop 30 s) | tree size |

Measured anchors and projections are kept separate; wall times are order-of-
magnitude, not promises.

---

## N. Stop conditions (locked for M013-B/C)

**HARD STOP — abort the run, keep the trial DB for post-mortem:**

1. Eligible physical files **> 500 000**.
2. `semantic_state` rows **> 2 000 000** or embedding vectors **> 2 000 000**.
3. Free disk **< 2× projected growth** or **< 100 GB** absolute.
4. Extraction/embedding process RSS **> 8 GB**.
5. Post-scan reconcile **> 30 s**.
6. Any write inside a selected source root attributable to the tool (new file,
   mtime change, sidecar, temp).
7. `PRAGMA integrity_check` ≠ `ok`, or any duplicate path.
8. Sustained WAL **> 256 MB**.
9. VRAM **> 23.5 GB** during embedding, or any CUDA OOM.
10. Archive statuses `LIMIT_*` **> 5 %** of canonical archives without a
    corresponding bounded-status explanation.
11. Sustained scan throughput **< 2 000 files/s**.
12. App/runtime instability (crash, hung worker, repeated exceptions).

**SOFT STOP (pause, record, request review):** `NOT_ARCHIVE_FORMAT` > 60 % of
canonical archives; malformed Office > 30 %; extraction success < 50 %.

---

## O. Selected-root manifest

Machine-readable and sanitised: **`docs/M013_CORPUS_MANIFEST.json`**
(schema `m013-corpus-manifest/v1`). It records root order, per-root eligible
counts/bytes, canonical archive counts/bytes, key format counts, inclusion
rationale, exclusion notes and the totals below.

```
eligible_physical_files : 303562
eligible_bytes          : 1013234649991  (1013.2 GB)
canonical_archives      : 7124           (90.3 GB)
pdf 4209 | office 1948 | email 195 | text 51711 | code 30574
image 98888 | archive 8267
```

No per-file names are stored.

---

## P. Source-safety verification

* Discovery used `os.scandir` + `lstat` only; file **contents** were opened only
  for the bounded extraction/archive-header samples (read-only `open(...,'rb')`
  / extractor reads). No source file was written.
* No temp/sidecar artefacts were found in source roots.
* `mtime < 180 min` count was **0** for Desktop, Zotero, Documents and Calibre;
  the small counts elsewhere are unrelated (Projects = active git/pytest
  `__pycache__`/`.validation` churn from the previous validation, plus this lot's
  committed tooling; Téléchargements = live browser downloads). The M013 tools
  never write outside `/home/chu/.pis-trials/` and the repo's `scripts/bench/`,
  `tests/unit/`, `docs/`.
* Symlink directories are never followed (0 in the selected roots).
* **Bounded proof used:** read-only syscall discipline + absence of tool-created
  temp/sidecar files + per-root mtime scan. A full hash tree was not required.

---

## Q. M013-B exact execution plan (SCAN + LIFECYCLE + FTS + ARCHIVES)

```
TRIAL_DB   = /home/chu/.pis-trials/m013b/files.db        # fresh, never production
EVIDENCE   = /home/chu/.pis-trials/m013b/evidence
LOGS       = /home/chu/.pis-trials/m013b/logs
ROOTS      = Desktop, Projects, Téléchargements, Zotero, Documents, Calibre Library

ENV:
  PIS_DB_PATH=/home/chu/.pis-trials/m013b/files.db
  PIS_SCAN_WORKERS=1  PIS_EXTRACT_WORKERS=1  PIS_ARCHIVE_WORKERS=1  PIS_OCR_WORKERS=8
  PIS_DB_BATCH_SIZE=1000  PIS_BULK_INDEX=1  PIS_SCAN_OVERLAP=0
  PIS_OCR_ENABLED=0
  PIS_ARCHIVE_ENABLED=1  PIS_ARCHIVE_POLICY=SAFE_SUPPORTED_MEMBERS
  PIS_ARCHIVE_MAX_DEPTH=3 PIS_ARCHIVE_MAX_MEMBERS=5000
  PIS_ARCHIVE_MAX_MEMBER_BYTES=67108864 PIS_ARCHIVE_MAX_TOTAL_UNCOMPRESSED=1073741824
  PIS_ARCHIVE_MAX_RATIO=200 PIS_ARCHIVE_TIMEOUT=30
  PIS_BLAS_THREADS=16  PIS_EMBEDDING_BATCH_SIZE=128  PIS_EMBEDDING_FP16=1
  PIS_AI_MODE=local  PIS_REMOTE_CONTENT_POLICY=never  PIS_LAUNCH_PROFILE=smart
```

Driver: one `ScanRequest(root, batch_size=1000)` per root through
`ScanService.run` (canonical `begin_scan → record_scan_files → complete_scan`
lifecycle), in the locked order. Then archive indexing via `ArchiveIndexer`
over canonical extensions (reuse M010 `run_archives.py`).

* Scanner batch size **1000**; bulk indexing **on**.
* Archives **on**, policy `SAFE_SUPPORTED_MEMBERS` (metadata + safe members).
* OCR **off**; AI **off/local**.
* Logging/evidence under `/home/chu/.pis-trials/m013b/`.
* Timeout: 30 min per root (SIGTERM → `fail_scan`), 30 min archive phase.
* Measurement interval: sample RSS/CPU/VRAM/disk every 5 s; per-root
  before/after snapshots.
* Stop checks: `counts`, `duplicate paths`, `PRAGMA integrity_check`, WAL size,
  free disk, source-write probe (section N) before and after each root.

**Explicitly out of scope for M013-B:** full extraction, embeddings, semantic
indexing, RAG.

Acceptance for M013-B: physical rows == 303 562 (±0 deletion), virtual members
bounded and explained, FTS rows == `files` rows, 0 duplicate paths, reconcile
< 30 s, no source writes, all statuses within limits.

---

## R. M013-C exact execution plan (EXTRACTION + EMBEDDINGS + SEMANTIC + RAG)

```
TRIAL_DB = /home/chu/.pis-trials/m013c/files.db   # copy of the validated m013b DB
```

1. **Sample extraction first:** bounded stratified sample (≥1 000 docs) to
   confirm success/malformed rates against section G; abort to review if success
   < 50 %.
2. **Full extraction** of content-bearing documents (~71k) with
   `PIS_EXTRACT_WORKERS=1`, OCR off, 50 MiB cap. Expect 15–85 min, RSS < 8 GB.
3. **Embeddings:** local `BAAI/bge-m3`, fp16, batch 128, BLAS 16. Ensure
   `ollama ps` is empty before starting (VRAM is the tight resource: peak 23.9 GB
   in M010). Monitor VRAM every 5 s; fall back 128→64→32 on pressure.
   Expect ~71k vectors ≈ 80 min.
4. **pgvector trigger:** if projected/actual vectors **> 100 000** (likely at
   500k; possible if extraction exceeds section G), run `scripts/bench/bench_pgvector.py`
   as a **required** comparison before declaring semantic readiness.
5. **Semantic freshness:** M011 incremental dirty-state; verify no-change sweep
   is O(1) (~ms) and that a 1-document change touches O(1) rows.
6. **Mutation/restart tests:** M010 `run_mutation.py` + `run_restart.py` against
   the trial DB / sandbox **only**; never against source trees.
7. **RAG sampling:** reuse `scripts/eval_retrieval.py` / `bench_rag.py` on a
   bounded query set; verify provenance and no reasoning-channel leakage.
8. **GPU safety:** stop on VRAM > 23.5 GB or CUDA OOM; keep Ollama unloaded
   during embedding.

---

## S. Hostile preflight review

| Attack | Finding | Class |
|---|---|---|
| Hidden duplicate roots | `Dropbox` mirrored 661 Desktop files | **REBUTTED** (excluded) |
| Nested roots / bind mounts | none; `mount_escape_files=0` | REBUTTED |
| Backup mirrors | `Desktop/Sauvegarde_*` is the primary corpus, not a copy of a selected root | REBUTTED |
| Archive bombs | `.tar.gz` with 5 000 members and 1.5 GB hit bounded `LIMIT_*`; limits enforce depth/members/size/ratio/timeout | **MINOR** (monitor) |
| Very large files | `.mkv/.mp4` > 50 GB exist; metadata-only, extraction cap 50 MiB | REBUTTED |
| Unreadable trees | 0 permission errors | REBUTTED |
| Sparse files | 0 special files in selected roots | REBUTTED |
| Symlink loops | symlinked dirs never followed; 0 symlink dirs | REBUTTED |
| Millions of tiny files | 88k jpg + 55k mp3; scan is metadata-only | REBUTTED |
| Giant vendor dirs | Android SDK / Tools / Applications / `.venv` / `node_modules` pruned or rejected | REBUTTED |
| DB growth underestimation | wide low/expected/high band from measured bytes/row | REBUTTED |
| Vector-count underestimation | measured extractor coverage + extensionless uncertainty → high band 92k | **MINOR** |
| Disk-margin optimism | 1.7 TB free vs ≤6 GB | REBUTTED |
| Scan-time optimism | conservative 2 000 files/s floor | REBUTTED |
| Archive-member explosion | bounded; one member-count limit observed | **MINOR** |
| OCR candidate explosion | ~1 300 image PDFs + 98 888 images; OCR off | **MINOR** (keep off) |
| Source mutation | additive tooling only; read-only discovery; code freeze required | **MINOR** (process) |
| Repo self-inclusion | `/home/chu/Projects` includes this repo → M013-B/C must run from a frozen commit | **MINOR** |

No BLOCKER or MAJOR survived review. All bounded fixes were applied (Dropbox
excluded; corpus kept single-volume; OCR off; archive limits locked).

---

## T. Defects / issues found

1. **MINOR — Dropbox mirror** (661 files). Fixed by exclusion.
2. **MINOR — repo self-inclusion** creates a corpus/code-freeze coupling. Fixed
   by process (freeze commit before M013-B/C).
3. **MINOR — VRAM headroom** (BGE-M3 fp16 = 23.9/24.0 GB). Fixed by requiring
   Ollama unloaded + batch fallback.
4. **MINOR — fake archives:** ~51 % of canonical extensions are
   `NOT_ARCHIVE_FORMAT` (proprietary files with archive-like names). Expected;
   handled by deterministic rejection, but archive-time estimates stay wide.
5. **INFO — Documents root is tiny** (354) because `.venv` is pruned; not a bug.
6. **INFO — pre-existing** ruff (7 046 findings) and mypy (1 147 errors) remain
   red in the repo; unrelated to M013.

---

## U. Commits

Local commits only (no push). See section V for the exact patch. Contents:
the preflight tool, its regression test, this report and the sanitised manifest.
No product/runtime code changed.

---

## V. Regression

Required gates for this lot:

```
.venv/bin/python -m pytest -q                     # all green
.venv/bin/python scripts/audit_repo.py            # PASS
git diff --check                                  # clean
.venv/bin/python -m pytest tests/unit/test_m013_preflight.py -q   # 8 passed
```

`run_validation.py` is run because a new script/test was added (see report).
Pre-existing ruff/mypy findings are unchanged and out of scope.

---

## W. BLOCKER / MAJOR / MINOR

* **BLOCKER:** none.
* **MAJOR:** none.
* **MINOR:** archive-member bombs (bounded), vector-count uncertainty
  (high band 92k), OCR explosion (OCR off), VRAM headroom (Ollama unloaded +
  batch fallback), repo self-inclusion / code freeze, Dropbox mirror (excluded).

---

## X. GO / NO-GO for M013-B

**GO.** The selected corpus is real, single-volume, 303 562 eligible physical
files (well inside 250k–500k), with 7 124 canonical archives and broad format
diversity. All stop conditions are satisfiable with current hardware and disk
headroom. Residual risks are MINOR and have concrete mitigations.

**Conditions:** run from a frozen commit; keep OCR off and Ollama unloaded;
enforce the section-N stop checks; never point any trial at the production DB.
