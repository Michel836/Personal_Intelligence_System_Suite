# Timeline, Relationship Graph & Prioritization (M016)

M016 adds a **local-only**, provenance-aware timeline, a bounded relationship
graph and an explainable prioritization layer. It queries the existing canonical
tables (M014 duplicates/versions, M015 entities/categories/PII, archive members,
tags/favorites) instead of creating a parallel relationship model or a separate
graph database.

New package: `src/graph/` (`relations.py`, `timeline.py`, `metrics.py`,
`priority.py`, `graph.py`). UI page: **🧭 Timeline & Graph** (core capability
`graph`). NetworkX and Plotly (already installed) are used for layout/rendering.

## Relationship types

| Type | Direction | Score / evidence | Source |
|---|---|---|---|
| `EXACT_DUPLICATE` | undirected | 1.0 · digest | `content_hashes` |
| `NEAR_DUPLICATE` | undirected | semantic score · reason | `near_duplicate_edges` |
| `VERSION_OF` | **directed** | family confidence · rank | `version_members` |
| `SEMANTIC_RELATED` | undirected | cosine · reason | embedding store (opt-in) |
| `ARCHIVE_CONTAINS` | **directed** parent→member | 1.0 · role | `files.archive_parent_id` |
| `SAME_ENTITY` | undirected | entity confidence | `doc_entities` |
| `SAME_CATEGORY` | undirected | category score | `doc_categories` |
| `SAME_LANGUAGE` | undirected | language confidence | `doc_language` |
| `PATH_CONTEXT` | undirected | 0.3 · parent_dir | `files.parent_dir` |
| `USER_TAG` | undirected | 1.0 · tag | `file_tags` |
| `FAVORITE` | undirected | 1.0 | `favorites` |
| `TEMPORAL_PROXIMITY` | undirected | window days | `files.modified_at` |

Each `Relation` exposes `source`, `target`, `type`, `score`, `evidence`,
`directed` and `provenance`. High-degree types (`SAME_CATEGORY`,
`SAME_LANGUAGE`, `PATH_CONTEXT`, `TEMPORAL_PROXIMITY`) are **opt-in** and always
bounded. `SAME_ENTITY` evidence explicitly states "both documents mention this
entity". **No relation asserts that a person knows, works with or owns anything.**

## Timeline

Date sources are kept distinct and each event carries its source + confidence:

| Source | Confidence | Meaning |
|---|---|---|
| `modified_at` | HIGH | filesystem modification time |
| `created_at` | MEDIUM | filesystem creation time (when the OS provides it) |
| `indexed_at` | LOW | when the application indexed the document (not a document date) |
| `version_date` | MEDIUM | explicit date parsed from the file name |

Grouping by day/week/month/year; filters by root, language, category, entity,
PII sensitivity and file type. Missing dates are **not invented** — the event is
omitted rather than given a fabricated timestamp.

## Graph bounds

`neighborhood(file_id, depth ≤ 2, max_nodes, max_edges)` performs a bounded BFS
over the relation service. `entity_graph(...)` caps entities and edges and, when
co-occurrence is requested, **excludes PERSON/ORGANIZATION** from entity–entity
edges to avoid implying social relationships. UI caps default to 50 nodes / 120
edges (up to 200/500).

## Prioritization

Transparent weighted sum over named signals; every contribution is returned.

| Signal | Weight | Notes |
|---|---|---|
| favorite | 3.0 | user signal (dominant) |
| user tag | 2.0 | user signal (dominant) |
| query name/path match | 1.5 | lexical relevance |
| entity match | 1.0 | query matches a mention |
| relationship centrality | 1.0 | bounded log(degree) |
| category relevance | 0.5 | top topic score |
| recency | 0.5 | exp(-age/365 days) |
| duplicate suppression | −0.5 | non-primary copy |

`score = Σ(value·weight)/Σweight − penalties`, clamped to `[0,1]`.
**PII/sensitivity is a filter, never an importance signal.** No destructive
automation is driven by the score.

## Centrality limits

Only bounded-subgraph metrics run: degree / weighted degree, connected
components, and PageRank on the bounded neighborhood (≤200 nodes; degree-
centrality fallback). No whole-corpus centrality, no O(N²).

## Storage decision

SQLite is sufficient: all one-hop/two-hop neighborhood, entity, timeline and
priority queries run in milliseconds over the existing indexed tables; no
Neo4j/graph database is added. The relation layer is a **query facade**, not a
duplicated store, so there is nothing to rebuild or keep in sync.

## Privacy

Graph/timeline views show masked PII only, never raw fingerprints as labels;
sensitivity filters and the remote-content policy apply; all processing is local.
Shared entities are surfaced as co-mentions, never as human relationships.

## Measured (M013/M014 corpus copy, bounded)

From `scripts/bench/bench_graph.py` on a copy carrying M014 relations and a
5,000-document M015 intel seed (aggregate only):

| Query | p50 | p95 |
|---|---:|---:|
| Timeline range (month group) | 44 ms | 52 ms |
| 1-hop neighborhood | 19 ms | 35 ms |
| 2-hop bounded neighborhood | 137 ms | 306 ms |
| Priority computation | 20 ms | — |
| Entity graph (200 entities / 1,000 edges) | 143 ms | — |
| Graph spring layout (50/100/500 nodes) | 7.4 / 0.7 / 0.6 ms | — |

Average 1-hop neighborhood: 17 nodes / 17 edges. Relation tables at this scale:
34,219 near-duplicate edges · 49,432 version members · 20,573 entities ·
55,389 archive links. DB growth from the run ~13 MB (indexes + seed).

**Storage decision:** SQLite is sufficient at 10k+ edges and 300k+ documents; no
graph database is added. Exact-duplicate edges appear once content hashes have
been computed (`content_hashes` is empty in this benchmark copy).
