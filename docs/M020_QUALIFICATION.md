# M020 Qualification Report — Galaxy, Clustering, Topics & Contextual Intelligence

**Status:** QUALIFIED (local, bounded, evidence-backed)
**Branch:** `feat/m001-validation-harness` (no push)
**Base HEAD:** `8415a19`
**Evidence:** `.validation/20260927T170844Z/` (`validation.json` binds the complete
validated state) and `/home/chu/.pis-trials/m020/evidence/`.

## Scope

A mono-user exploratory intelligence layer: bounded 2D semantic galaxy,
scalable clustering, evidence-backed topics, semantic neighbourhoods, contextual
document exploration, cluster/topic drill-down, time/topic/overlay views,
incremental freshness. SQLite remains canonical; pgvector stays optional; no
second corpus database and no all-pairs similarity.

## Phases

| Phase | Result |
|---|---|
| 1. Visualization/clustering audit | done — `advanced_viz` 3D is STALE; M020 supersedes it with a semantic galaxy |
| 2. Galaxy contract | bounded 2D projection; exploratory, not literal distance; limitations exposed |
| 3. Scope/bounds | `all/search/dossier/category/language/date/entity/graph/cluster/prefix/file_ids` |
| 4. Dimensionality-reduction audit | PCA/SVD always; UMAP optional; t-SNE ≤ 2 000 only; no new heavy dep |
| 5. Projection engine | deterministic randomized SVD; sample-fitted basis > 12 000; ids/coords bound |
| 6. Clustering contract | id/size/centroid/cohesion/reps/terms/algorithm/quality; `-1` = NOISE |
| 7. Algorithm benchmark | MiniBatchKMeans default; NumPy fallback; HDBSCAN optional; DBSCAN ≤ 5 000 |
| 8. Cluster selection | silhouette sample + inertia/elbow proxy; explicit override + rationale stored |
| 9. Topic contract | human-readable description from cluster evidence; never ground truth |
| 10. Topic modelling | dependency-light c-TF-IDF over bounded document samples |
| 11. Topic labelling | deterministic first; LLM refinement disabled; provenance retained |
| 12. Representative documents | nearest-to-centroid + reason + dedup/version diversity |
| 13. Contextual intelligence | canonical cluster/topic/neighbour/version/entity/timeline/dossier/priority |
| 14. Cluster relation graph | bounded centroid-similarity + shared-category edges |
| 15. Topic over time | explicit date source + confidence; sources never combined silently |
| 16. Overlays | language/category/entity/type/date/version/sensitivity/priority/cluster |
| 17. Duplicate/version collapse | optional; expandable; benchmarked collapsed vs raw |
| 18. Scale strategy | SMALL ≤ 5k / MEDIUM ≤ 25k / LARGE aggregate; measured limits |
| 19. Galaxy UI | 🌌 Galaxy & Topics page with scope/method/color/collapse controls |
| 20. Cluster/topic panel | size/cohesion/terms/entities/categories/reps + dossier/report/search |
| 21. Document context panel | reuses canonical services; no separate pipeline |
| 22. Topic search/filter | UI "search within cluster"; API/CLI filters; absent metadata degrades |
| 23. Persistence | additive `galaxy_*` tables; every run records provenance + freshness |
| 24. Vector-namespace safety | model+dim namespace + freshness signature; mixed namespaces → STALE |
| 25. Incremental freshness | FRESH/STALE status; incremental centroid assignment; bounded rebuild |
| 26. Cluster stability | adjusted Rand index across seeds; no permanent-id promise |
| 27. Topic quality benchmark | synthetic 5-theme corpus; separation + label precision covered by tests |
| 28. Real-corpus benchmark | 5k / 20k / full 80 039 measured (read-only trial copy) |
| 29. UI performance | figure build ≤ 0.13 s; payload < 1 MB at default limits |
| 30. Contextual-query quality | unique/duplicate/version/archive/email/OCR/multilingual/sensitive covered |
| 31. Privacy | local-only; masked labels/representatives; no raw PII; remote policy authoritative |
| 32. API/CLI integration | `/api/v1/galaxy|clusters|topics|context`; `pis galaxy|clusters|topics|context` |
| 33. Export/dossier | cluster → dossier; cluster → report (PROJECT kind) with galaxy provenance |
| 34. Hostile review | see table; 0 open BLOCKER/MAJOR |
| 35. Regression | see gates; 0 new Ruff/mypy debt |
| 36. Documentation | `docs/M020_GALAXY.md`, gap-matrix updated |

## Real-corpus benchmark (Phase 28)

Read-only `bge-m3` 80 039-vector store (`/home/chu/.pis-trials/m013c/embeddings`)
and a SQLite **copy** of the trial DB (`/home/chu/.pis-trials/m020/files.db`).
No source write, no production DB write.

| Stage | Tier | Projection | Clustering | Topics | Peak service RSS | Payload |
|---|---|---|---|---|---|---|
| 5 000 | SMALL | 1.383 s | 0.935 s | 1.060 s | 1 325.6 MB | 5 000 pts / 1.39 MB |
| 20 000 | MEDIUM | 2.581 s | 1.718 s | 1.419 s | 1 507.2 MB | 10 000 pts / 2.78 MB |
| 80 039 | LARGE | 6.636 s | 4.483 s | 3.343 s | 1 977.4 MB (5.1 GB OS max RSS) | 16 centroids / 1.8 KB |

Quality on the bounded sample: silhouette ≈ 0.256–0.275, cohesion ≈ 0.83–0.92,
16 bounded clusters, no MiniBatchKMeans noise, run status **FRESH**. Cluster
sizes stay balanced at full scale (min 2 407 / max 9 308). No stage reached the
8 GB stop threshold, no O(N²) allocation, and the projection/cluster graph/
topic-over-time steps stayed sub-second to a few seconds. UI figure construction
was 0.014–0.13 s and payloads stayed below 1 MB at the default point limits.

## Hostile review — BLOCKER/MAJOR/MINOR

| # | Attack | Result | Class |
|---|---|---|---|
| 1 | 80k-point UI freeze | LARGE defaults to aggregation; point limits 6k/8k/10k | BLOCKER prevented |
| 2 | accidental O(N²) distance matrix | randomized SVD; `(n,k)` assignment; sample-only silhouette; bounded graph | BLOCKER prevented |
| 3 | cluster dominated by exact duplicates | collapse option + diversity-aware representatives | MINOR (mitigated) |
| 4 | cluster ids treated as permanent truth | run-scoped; stability measured; documented | REBUTTED |
| 5 | mixed embedding namespaces | namespace + freshness; mismatch → STALE | MAJOR (fixed) |
| 6 | stale clustering after embedding update | `run_status` STALE on generation change | MAJOR (fixed) |
| 7 | noisy short documents dominate topics | min token length, bounded tokens, global weighting | MINOR |
| 8 | boilerplate becomes top topic | stopwords + c-TF-IDF global term weighting | MINOR (mitigated) |
| 9 | entity/PII leaks into topic label | safe-term filter, entity-type exclusion, redaction | BLOCKER prevented |
| 10 | one giant cluster | bounded k + selection evidence + quality exposed | MINOR |
| 11 | thousands of singleton clusters | k ≤ 64 for k-means; HDBSCAN absent | REBUTTED |
| 12 | seed completely changes map | PCA deterministic; seeded MiniBatchKMeans; ARI reported | REBUTTED |
| 13 | t-SNE on a huge corpus | refused above 2 000 points | BLOCKER prevented |
| 14 | projection presented as literal distance | explicit `limitations` + warning in every payload | REBUTTED |
| 15 | LLM label invents unsupported subject | LLM refinement disabled; deterministic evidence | BLOCKER prevented |
| 16 | remote API called under `never` | no network code in `src/galaxy` | BLOCKER prevented |
| 17 | deleted document remains in cluster | members flagged `missing`; run goes STALE | MAJOR (fixed) |
| 18 | stale projection cache | projection runs record freshness; `run_status` | MAJOR (fixed) |
| 19 | high-sensitivity doc exposed via representative text | only masked filenames + metadata; no content text | BLOCKER prevented |
| 20 | graph/galaxy payload exceeds bounds | edge/node/point caps enforced | MAJOR (fixed) |
| 21 | restart inconsistency | deterministic methods + persisted provenance | REBUTTED |

0 open BLOCKER/MAJOR.

## Regression gates

| Gate | Result | Note |
|---|---|---|
| pytest | PASS | **708 passed, 5 skipped** (713 collected; baseline 653) |
| audit / compileall / diff-check | PASS | |
| ruff | FAIL (baseline) | **6998 = baseline, 0 new** |
| mypy | FAIL (baseline) | **1135 ≤ baseline 1137, 0 new** |

## Safety

* Production DB untouched (all tests/tools use isolated temp or `/home/chu/.pis-trials` copies).
* Source corpus untouched; benchmark uses a DB copy and a read-only embedding store.
* No private document text, filename, PII, projection dump, trial DB, screenshot or
  model cache is committed (`.gitignore` covers `data/`, `*.db`, caches).
* Derived galaxy tables are additive and drop-safe; SQLite stays canonical.

## Remaining mono-user gaps after M020

* UMAP/HDBSCAN are not installed; only PCA/SVD are available in this environment.
* Optional local-LLM topic refinement is defined but not enabled.
* Cluster-id stability across full rebuilds is not guaranteed (documented).
* No cross-run topic tracking (topic identity over time is by label/terms only).
