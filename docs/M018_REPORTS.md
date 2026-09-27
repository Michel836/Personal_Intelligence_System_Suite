# Reports, PDF Export, Dossiers & Evidence Packs (M018)

M018 turns indexed/searchable intelligence into **usable deliverables**:
reports, PDFs, dossiers/projects and evidence packs. It is **local-only**: no
cloud conversion, no source-file modification, no parallel document database,
no fabricated citations, and no compliance/legal guarantees.

New package: `src/reports/` (`models.py`, `citations.py`, `provenance.py`,
`privacy.py`, `store.py`, `dossiers.py`, `reconstruction.py`, `builders.py`,
`html_export.py`, `pdf_export.py`, `export.py`, `summary.py`). UI page:
**📁 Dossiers & Reports** (capability `reports`). Benchmark:
`scripts/bench/m018_reports.py`.

## Report model

A report is a **reproducible definition** plus rendered **artifacts**, never a
copy of documents:

* `ReportDefinition` — report id, kind, title, description, created-at, source
  query/filter, included document ids, privacy mode, options;
* `ReportIR` — renderer-agnostic structured content: ordered `sections` of typed
  `blocks` (heading, paragraph, table, document card, citation, image, timeline,
  graph summary, warning, metadata, source appendix, summary), the `sources`
  (provenance), warnings, omitted items and the optional AI summary;
* `ReportManifest` — generation timestamp, generator version, privacy mode,
  logical fingerprint, source ids and content hashes, artifacts + checksums,
  warnings and omitted items.

Report kinds: `SEARCH`, `DOSSIER`, `TIMELINE`, `DUPLICATES`,
`ENTITY_CATEGORY`, `PII_SUMMARY`, `INGESTION`, `PROJECT`. Every kind is assembled
from canonical services (lexical search, dedup, graph/timeline, intel, ingest) —
no report type re-implements business logic.

## Provenance

Each factual item carries how it was obtained:

| Class | Meaning |
|---|---|
| `KNOWN` | read directly (filesystem mtime, a real email header date, a stored content hash) |
| `DERIVED` | computed from a canonical service (version rank, relation, aggregate) |
| `INFERRED` | heuristic (e.g. a filename version marker) |
| `UNAVAILABLE` | not provided by any source — reported as such, never invented |

Sources expose file id, display filename, privacy-safe path, document date +
date source, extraction state, relation type/evidence, search score and a
page/section location **only when the extractor actually provided one**.

## Citation semantics

Reference grammar, stable within a report and assigned in first-seen order:

* `[D12]` document · `[D12:p3]` document with a real page/section · `[E7]`
  entity · `[V3]` version family · `[M4]` email message · `[A2]` archive.

Invariants: every reference resolves to a registered source; a citation to a
document that no longer exists is marked **unavailable**, never dropped silently;
page locations are never fabricated (`citation_with_location` only emits `:pN`
for a real numeric location); the source appendix lists every reference.

## PDF export

One canonical path — the standalone HTML — rendered by the first available
**local** provider, in order:

1. **WeasyPrint** (pure Python, best `@page` support) when importable;
2. **LibreOffice** headless (already used by legacy extraction);
3. **google-chrome** headless `--print-to-pdf`.

The chosen provider and version are recorded in the manifest. If none is
available the PDF is skipped explicitly (HTML + JSON are still produced); there
is no silent, content-changing fallback. Every run is isolated in a temp
profile, bounded by a timeout (240 s) and an output cap (300 MB), and the PDF is
validated (openable, ≥ 1 page) before an atomic move into place.

**Bounds / safety:** included documents, table rows, cards, thumbnails and
output size are capped by the assembler and the renderer; one malformed asset
(missing image/source) degrades to a warning, never a crash.

## Dossiers (static vs dynamic)

A dossier is a *view* over the canonical `files` table.

* **STATIC** — an explicit, ordered document set. Never silently changed.
* **DYNAMIC** — resolved from a saved query/filter at read time. The current
  match count, last refresh, added/removed/missing delta and an optional frozen
  snapshot are always exposed.

**Manual membership wins:** manually added documents are pinned even when the
query does not match them; explicitly excluded documents stay out. Workflow:
create, rename, add/remove, reorder, notes, sections, attach a saved query,
refresh, freeze snapshot, compare snapshot vs current. No destructive source
action.

## Reconstruction contract

Reconstruction assembles related material into an evidence pack; it never
invents missing documents or chronology.

* **Versions** — ordered only on an explicit version marker (HIGH confidence);
  ambiguous families are shown unordered; a "current/final" version is flagged
  only with an explicit marker, never from newest mtime; optional bounded text
  diff.
* **Email threads** — RFC headers only (M017); sender/recipient parsed from the
  stored message text and masked per mode; no subject-based joining.
* **Archives** — parent + already-indexed members; never re-expanded.
* **Duplicates** — exact (content hash) + near (canonical dedup store).
* **Timeline** — date source and confidence preserved.

## AI-assisted summary (optional)

Summarisation is **optional** and never required for report creation. It is
policy-aware (goes through the M012 router; under `never` only local providers
are offered, so zero external traffic), source-bounded (only excerpts already in
the report, each prefixed with its citation), and citation-grounded: references
are re-validated against the provided set and any other reference is dropped. It
is always labelled "AI-generated summary" and states when evidence is
insufficient. It never cites a source it did not receive.

## Privacy modes

| Mode | Content | Path |
|---|---|---|
| `FULL_LOCAL` | full excerpts | full path (warns if high-sensitivity PII is included) |
| `MASK_PII` | PII masked in excerpts | PII masked in filenames |
| `OMIT_HIGH_SENSITIVITY` | non-high-sensitivity only | full path |
| `PATH_REDACTED` | full excerpts | directory removed (`<redacted>/name`) |
| `METADATA_ONLY` | no excerpts | directory removed |

A mode is never silently downgraded; the chosen mode is recorded in the
definition, manifest and rendered banner, and the UI previews what will be
exported before generation. Masking is a derivative only — the original is never
modified, and raw values never reach logs, temp names or PDF metadata.

## Export manifest & reproducibility

Every artifact has a manifest with report id, generation timestamp, app/generator
version, source document ids, source content hashes where available, privacy mode,
exporter, output checksum, warnings and omitted items. Same definition +
unchanged inputs → **stable logical content** (sections, source ids, citations,
manifest, text representation). **Byte-identical PDF is not claimed** (renderers
embed timestamps/IDs); reproducibility is compared at the logical level via
`ReportIR.logical_fingerprint()`.

## Export directory

Configurable via `PIS_EXPORT_DIR` (default `~/.pis-exports`), never inside a
scanned source tree by default. Paths are joined safely and must resolve inside
the export directory; filenames are collision-resistant (report id + timestamp +
random suffix); writes are temp-then-atomic; existing artifacts are never
overwritten silently.

## UI

**📁 Dossiers & Reports** has tabs *My dossiers*, *Create dossier*, *Build
report*, *Export* and *History*. The Search results and Timeline/Graph pages
expose an "Add to dossier" action; the graph action only offers the nodes already
shown by the (filtered) graph service, so hidden/sensitive nodes are never added
silently.

## Measured (M013–M017 trial data, aggregate only)

From `scripts/bench/m018_reports.py` (trial dirs under `/home/chu/.pis-trials/m018/`;
no filename, path or excerpt is recorded):

| Report | Sources | Assembly | HTML | PDF | Output |
|---|---:|---:|---:|---:|---:|
| Search 50 (with excerpts) + PDF | 50 | 2.88 s | 1 ms | 0.49 s | 464 KB HTML · 261 KB PDF |
| Dynamic dossier 100 (masked, metadata) | 100 | 0.89 s | 1 ms | — | 61 KB |
| Timeline slice | 200 | 0.07 s | 1 ms | — | 75 KB |
| Duplicate groups | 118 | 0.60 s | 1 ms | — | 50 KB |
| Entity/category | 100 | 0.96 s | 1 ms | — | 74 KB |
| PII summary (masked) | 200 | 0.16 s | 2 ms | — | 120 KB |
| Ingestion health | — | 0.07 s | <1 ms | — | 5 KB |
| Version reconstruction | 2 | 2 ms | — | — | — |
| Email-thread reconstruction | 2 | 2 ms | — | — | — |

Peak RSS ≈ 1.17 GB for the full multi-report run. PDF quality (synthetic: FR/DE/EN
Unicode, 200-row multi-page table, long URL, citations, masked PII, missing
source/image) renders multi-page with selectable, correct Unicode text.

## Known limitations

* **PDF byte determinism** is not claimed (renderer timestamps/IDs).
* **Page-number counters** are emitted via CSS `@page` margin boxes; they render
  in WeasyPrint/browser print, and are **not guaranteed** under LibreOffice/Chrome
  headless.
* **PST/OST** remain unsupported (M017 dependency bound); reports cannot cite
  what was never extracted.
* The summariser depends on an available LLM provider; without one the report is
  still produced and the summary is marked unavailable.
* PII detection is the conservative M015 detector; masking is regex-based and
  may miss unusual formats (a report is a derivative, not a compliance artefact).
