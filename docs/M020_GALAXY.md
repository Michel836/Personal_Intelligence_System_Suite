# Galaxy, Clustering, Topics & Contextual Intelligence (M020)

M020 adds a **bounded, mono-user, local-only** corpus-navigation layer on top of
the canonical SQLite corpus and the existing semantic embedding store. It is
exploratory: nothing here is a second corpus database, no algorithm is allowed
to allocate an all-pairs distance matrix, and no content leaves the machine.

New code: `src/galaxy/` (`text`, `projection`, `clustering`, `topics`, `store`,
`service`), the **🌌 Galaxy & Topics** UI page (`src/ui/galaxy_page.py`), and the
`/api/v1/galaxy`, `/api/v1/clusters`, `/api/v1/topics`, `/api/v1/context/{id}`
endpoints plus `pis galaxy|clusters|topics|context`.
Benchmark: `scripts/bench/m020_galaxy.py`.

## 1. What a "galaxy" is

A galaxy is a **bounded 2D projection of a selected corpus/subcorpus**. Each
point is one document, or one aggregate cluster when scale requires it.

* The projection is an **exploratory coordinate system**, not literal semantic
  distance. PCA/SVD preserve global variance; UMAP/t-SNE mainly preserve local
  neighbourhoods. The API always returns a `limitations` string and a warning.
* Signals available as overlays: semantic embedding, cluster, topic, category,
  language, date, file type, priority, entity and sensitivity.
* The projection method, version, sample/aggregation flag and vector namespace
  are returned with the payload and stored with any persisted run.

## 2. Scope and bounds

`resolve_scope` supports: `all`, `search`, `dossier`, `category`, `language`,
`date`, `entity`, `graph`, `cluster`, `prefix`, `file_ids`. Scopes are always
intersected with the embedding store, so only embedded documents can appear.

Scale tiers are chosen from measured behaviour, not hard-coded magic:

| Tier | Input | Default view | Point limit |
|---|---|---|---|
| SMALL | ≤ 5 000 | full raw interactive scatter | 6 000 |
| MEDIUM | 5 001–25 000 | sampled scatter | 8 000 |
| LARGE | > 25 000 | cluster centroids + density, drill-down | 10 000 |

`LARGE` defaults to aggregated cluster points; a caller can explicitly request a
bounded point sample instead. An 80 039-vector corpus is never rendered as 80 039
browser points.

## 3. Dimensionality reduction

`src/galaxy/projection.py`. Methods and their bounds:

| Method | Availability | Bound | Determinism |
|---|---|---|---|
| `pca` | always (NumPy randomized SVD) | none | deterministic |
| `svd` | always (uncentered variant) | none | deterministic |
| `umap` | only if installed | 20 000 | seeded |
| `tsne` | only if `scikit-learn` installed | **2 000** | seeded, exploratory |

The large-N path fits the basis on a deterministic sample (`FIT_CAP = 12 000`)
and transforms every vector, so cost stays near `O(N · dim)` and no `N×N` matrix
is ever built. PCA/SVD remain the dependable fallback. No heavy dependency was
added merely for visual appeal.

## 4. Clustering contract

Clusters are **similarity groups, not ground-truth categories**. Every run
exposes: cluster id, size, centroid (persisted as membership + similarity),
cohesion proxy, representative documents, representative terms/entities, the
algorithm/version and quality metrics. `-1` is reserved for **UNCLUSTERED /
NOISE** and is never silently equated with a topic.

Algorithms (`src/galaxy/clustering.py`): `minibatch-kmeans` (default, linear,
deterministic seed), `kmeans`, `hdbscan` (only if installed), `dbscan` (refused
above 5 000 points). A pure-NumPy fallback exists if `scikit-learn` is absent.

Cluster count is selected from evidence (`select_k`: silhouette on a deterministic
sample plus an inertia/elbow curve) and can always be overridden explicitly. The
selected parameters and rationale are stored.

Stability is measured with the adjusted Rand index across seeds
(`cluster_stability`); stable ids across a full rebuild are **not** promised.

## 5. Topic contract

A topic is a **human-readable description derived from cluster/content
evidence** — never an opaque AI label:

* c-TF-IDF terms over bounded per-cluster document samples (`src/galaxy/text.py`,
  no external NLP dependency);
* safe entities (PERSON/PII-typed entities are excluded from labels and masked in
  evidence);
* category signal and representative documents.

Labels are deterministic first. An optional local-LLM refinement is intentionally
**not** enabled by default and would have to retain the deterministic terms,
provenance, provider and fallback; under the `never` remote policy it must make
zero external calls. Evidence records `label_source = deterministic` and
`llm_refined = false`.

## 6. Representative documents

Nearest-to-centroid, with a stated reason, and diversity-aware: exact duplicates
and non-primary version members are skipped using the M014 dedup/version tables,
so a cluster is not dominated by copies. Each representative carries its
`similarity` and `reason`.

## 7. Contextual intelligence

`GalaxyService.document_context(file_id)` assembles canonical signals only:
cluster/topic membership, semantic neighbours (reusing the embedding store via
M014 `RelatedDocuments`), versions, duplicates, entities, categories, language,
PII metadata (masked), timeline neighbours, dossiers and the M016 priority score.
Relationship logic is never duplicated.

## 8. Cluster relation graph, topic-over-time and overlays

* **Cluster graph** (`cluster_graph`): aggregates only. Edges are bounded
  centroid-similarity (`neighbor_edges` per node) plus shared-category edges,
  capped at `max_edges`. No all-pairs corpus similarity.
* **Topic-over-time** (`topic_over_time`): explicit date source
  (`modified_at` / `created_at` / `indexed_at`) with a confidence label; sources
  are never silently combined.
* **Overlays**: language, category, entity, file type, date, version family,
  sensitivity, priority, cluster/topic — masked, PII-free.

## 9. Duplicate / version collapse

Before projecting/clustering a caller may collapse exact duplicates and version
families (`collapse_ids`), preserving the ability to expand them later (membership
is still stored). Both collapsed and raw behaviour are available and measured.

## 10. Persistence and rebuildability

Additive canonical tables: `galaxy_cluster_runs`, `galaxy_cluster_members`,
`galaxy_topics`, `galaxy_projection_runs`, `galaxy_projection_points`. Every run
records algorithm, params, **vector namespace** (model + dimension), freshness
signature, source scope, input count and software version. The tables are
**derived and drop-safe** (`GalaxyStore.rebuildable()`); dropping them never
touches the corpus.

## 11. Vector-namespace safety and incremental freshness

A run binds to `model_key:dim` and a freshness signature derived from the store
count and the semantic generation. When the embedding model/dimension changes or
documents are added/changed/deleted/refreshed, `run_status` reports **STALE**
instead of pretending the old clustering is current. `incremental_reassign`
assigns new documents to existing centroids without a full rebuild; a bounded
rebuild is always available.

## 12. Scale, quality and privacy

* No O(N²) allocation: projection fits on a bounded sample; clustering is linear;
  metrics run on a bounded sample; the cluster graph is bounded.
* Privacy: all processing is local; topic labels and representative text are
  masked via the M015 redactor; PII-derived terms are excluded from labels; the
  API masks paths by default and never returns raw PII. The M012 remote policy
  remains authoritative.

## 13. API / CLI

```
GET /api/v1/galaxy?scope=all&method=pca&color_by=cluster&k=16&limit=10000
GET /api/v1/clusters?build=1
GET /api/v1/clusters/{run_id}/{cluster_id}
GET /api/v1/topics
GET /api/v1/context/{file_id}
```

```
pis galaxy  [--scope ...] [--method pca|svd|umap|tsne] [--k N] [--persist]
pis clusters [--run-id ID] [--build] [--algorithm ...] [--k N]
pis topics  [--run-id ID]
pis context <file_id>
```

All commands support `--json`; payloads are bounded; the API is loopback-only and
masked by default.

## 14. Measured benchmark (real 80 039-vector store, trial copy)

See `docs/M020_QUALIFICATION.md` for the full evidence. Headline numbers
(Intel i9-14900 / 62 GB RAM, `bge-m3` 1024-d, read-only store + trial DB copy):

| Stage | Projection | Clustering | Topics | Peak service RSS |
|---|---|---|---|---|
| 5 000 | 1.4 s | 0.9 s | 1.1 s | 1.3 GB |
| 20 000 | 2.6 s | 1.7 s | 1.4 s | 1.5 GB |
| 80 039 (LARGE, aggregate) | 6.6 s | 4.5 s | 3.3 s | 2.0 GB |

Silhouette on the bounded sample ≈ 0.26–0.27, cohesion ≈ 0.83–0.92, 16 bounded
clusters, no noise for MiniBatchKMeans, status FRESH. UI figure construction
stays < 0.2 s and payloads < 1 MB at the default limits.

## 15. Known limitations

* Coordinates are approximate; PCA axes are not interpretable features.
* Topics describe cluster evidence; they are not ground truth and short/noisy
  documents or boilerplate can still influence terms (bounded sampling +
  diversity reduces but does not eliminate this).
* Cluster ids are run-scoped; there is no cross-rebuild id stability guarantee.
* UMAP/HDBSCAN are absent in the current environment and therefore unavailable.
* The optional local-LLM label refinement is defined but not enabled.
