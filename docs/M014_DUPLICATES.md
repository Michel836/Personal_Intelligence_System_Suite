# Duplicates, Versions, Related Documents & Reranking (M014)

M014 adds an evidence-based duplicate/version/related layer on top of the
existing canonical stack (SQLite `DatabaseManager`, lifecycle, extraction,
`semantic_state`/embedding store, archive members, provider router, launch
profiles). **Nothing is ever deleted, merged, renamed or moved.**

New package: `src/dedup/` (`store.py`, `hashing.py`, `exact.py`, `near.py`,
`versions.py`, `related.py`, `rerank.py`, `fingerprint.py`). New tables live in
the same canonical database: `content_hashes`, `version_families`,
`version_members`, `near_duplicate_edges`. UI page: **🧬 Duplicates & Versions**
(`src/ui/dedup_page.py`, core capability `duplicates`, available in every
profile; the semantic sections require the semantic capability + an embedding
store).

## Exact duplicates

* Identity is the **SHA-256 digest of the full file bytes** (strong content
  identity; never name/size/mtime alone).
* Hashing is **size-first and incremental**: only files whose size is shared with
  another candidate are read. A stored hash is invalidated when the file's
  `size_bytes` or `modified_at` changes; deletes are filtered by lifecycle state.
* States: `OK`, `TOO_LARGE` (above `ContentHasher.max_bytes`, default 1 GiB),
  `UNREADABLE` (retried later), `SKIPPED`. Zero-byte files hash to the known
  empty digest and are excluded by a minimum-size threshold by default.
* `ExactDuplicateEngine` exposes groups with a stable `sha256:<digest>` key,
  member ids/paths, size, count, `wasted_bytes = size × (copies − 1)`, physical
  vs archive-member counts and lifecycle state. Filters: `scope_prefix`,
  `min_size`, `max_size`, `include_members`, `include_missing`.
* Group member lists are capped (`max_members_per_group`, default 100) so a
  3,000-copy group cannot blow up the UI; true aggregate totals come from
  `duplicate_totals()` (not the capped list).

### Measured (M013-B corpus copy, 303,593 physical files)

| Metric | Value |
|---|---|
| Shared-size candidate sizes | 44,765 |
| Files hashed (≤ 50 MB) | 259,056 (112.1 GB read) |
| First pass | **143.6 s** (~1,805 files/s, ~780 MB/s) |
| Second pass (incremental) | **8.2 s, 0 re-hashed** |
| Hash coverage | 72.2 % of all active rows |
| Exact duplicate groups | **72,268** |
| Redundant copies | 99,217 |
| Reclaimable bytes | **57.9 GB** |
| Largest single group | 3,466 identical files |

## Near duplicates

* **Vector-hyperplane LSH** over the existing bge-m3 embedding store generates
  candidates (cosine-preserving, bounded, never an O(N²) pass), confirmed by
  exact cosine; a lexical **SimHash + LSH** fallback is used when no store is
  present.
* Exact duplicates (identical stored content hash) are **excluded** from the
  near-duplicate output.
* Each edge carries `semantic_score`, `lexical_score` and a `reason`
  (`semantic`, `semantic+lexical`, `candidate`). Threshold, `min_chars`,
  `max_docs`, `max_pairs` and `max_neighbors_per_doc` are configurable.
* Bounded graph: `max_pairs` caps candidate expansion; `max_neighbors_per_doc`
  (default 20) keeps only the strongest neighbourhood per document.
* The near-duplicate table is rebuilt atomically; stale/edge rows referencing
  inactive files are pruned (`prune_missing_relations`).

### Measured (M013-C store, 80,039 vectors / 63,911 active content docs)

| Metric | Value |
|---|---|
| Candidate pairs (cap 3 M) | 3,000,000 (truncated) |
| Near-duplicate edges (cosine ≥ 0.90, ≤ 20/doc) | **34,219** |
| Wall | **40.2 s** (vector LSH + confirmation) |
| Candidate source | `vector_lsh` |

## Version families

* Grouping by `(parent_dir, normalize_stem(name))`, where the stem strips
  explicit version markers: `vN`/`verN`/`revisionN`, `(N)`, dates
  (`YYYY-MM-DD`, `DD-MM-YYYY`, `YYYYMMDD`), and words such as
  `final/copy/old/new/backup/draft/...`.
* Confidence:
  * **HIGH** — ≥ 2 members carry an explicit numeric/date marker; ordered by the
    marker (dates before numbers), then modification time.
  * **MEDIUM** — version words present or high-similarity semantic support.
  * **UNORDERED** — stem match only; **no chronology is invented** (order falls
    back to modification time, labelled as such).
* Persisted as `version_families` + `version_members` (rank, confidence,
  evidence, primary/newest). Renamed/moved/deleted versions are handled by the
  lifecycle and by `prune_missing_relations` on rebuild.

### Measured

| Confidence | Families |
|---|---|
| HIGH | 2,129 |
| MEDIUM | 11–15 |
| UNORDERED | ~2,860 |
| Build wall | ~50–74 s (303,593 files; families capped at 5,000) |

## Related documents

`RelatedDocuments.related(file_id)` returns semantic nearest neighbours from the
store, excluding the source and (by default) missing documents, annotated with
`semantic_similarity`, `reason` and markers (exact group / near duplicate /
version family / archive). Measured p50 **29 ms**, p95 82 ms (20 samples).

## Reranking / fusion

`rerank_search()` retrieves lexical (FTS) + semantic candidates and fuses them
with **reciprocal rank fusion** (`1/(k+rank)`), plus a boost that guarantees an
exact filename/path match is never buried. Optional exact-duplicate collapse and
version-family diversity reduce repeated copies; `show_all_copies` /
`show_all_versions` restore them. When the semantic engine is unavailable the
result is pure lexical order (fallback preserved). Measured p50 ~0.7 s (dominated
by semantic query embedding; lexical-only is ~2–5 ms).

## Incremental freshness

* Content change → hash invalidated by size/mtime and re-computed on the next
  backfill; exact group membership updates.
* Delete/missing → excluded from groups; version families/near edges pruned on
  the next build so a lone member is no longer a family.
* Re-add → hashes and families are restored. Semantic dirty-state logic is
  unchanged (vectors refresh lazily as before).

## No destructive actions

The module and UI expose **suggestions only**. There is no delete/merge/rename/
move/dedup operation anywhere in M014, and no user file is ever written.

## Configuration (env)

| Env var | Default | Meaning |
|---|---|---|
| `PIS_ARCHIVE_EXTRACT_TIMEOUT` | `120` | per-archive member-extraction budget (M013-C2) |
| — | — | `ContentHasher(max_bytes=1 GiB)` is a constructor parameter |
| — | — | near-dup threshold/caps and version `max_families` are engine parameters |
