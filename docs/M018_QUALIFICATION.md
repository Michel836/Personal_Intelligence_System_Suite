# M018 Qualification Report — Reports, PDF Export, Dossiers & Evidence Packs

**Status:** QUALIFIED (local, bounded, evidence-backed)
**Branch:** `feat/m001-validation-harness` (no push)
**Base HEAD:** `4ce6d1e`
**Evidence:** the most recent `.validation/<UTC run>/` (its `validation.json` binds
the complete final state) and `/home/chu/.pis-trials/m018/evidence/`

## Scope delivered

Canonical `src/reports/` layer: report model + IR, provenance, citations, privacy
modes, persistent dossiers (static/dynamic), evidence-based reconstruction,
HTML/PDF/JSON export with manifests and reproducibility, optional citation-grounded
summary, and a **📁 Dossiers & Reports** UI page. All local; no parallel document
store; no source modification; no fabricated citations; no compliance claims.

## Phases

| Phase | Result |
|---|---|
| Existing report/export audit | completed (see `docs/M018_REPORTS.md`); legacy `scripts/utilities/*pdf*` are stale (missing `markdown`/`weasyprint`, remote fonts) and were not reused |
| Report contract | `ReportDefinition` + `ReportIR` + `ReportManifest` (reproducible) |
| Report types A–H | SEARCH/DOSSIER/TIMELINE/DUPLICATES/ENTITY_CATEGORY/PII_SUMMARY/INGESTION/PROJECT |
| Source provenance | KNOWN/DERIVED/INFERRED/UNAVAILABLE; no invented dates/pages |
| Citation model | `[D12]`/`[D12:p3]`/`[E7]`/`[V3]`/`[M4]`/`[A2]`; validated, no dangling |
| Content IR | renderer-agnostic typed blocks |
| HTML export | standalone, inline CSS, escaped, no remote assets, print layout |
| PDF export | provider chain weasyprint→libreoffice→chrome; provider recorded |
| PDF safety/bounds | timeout, size cap, validated output, explicit failure |
| Dossier model/workflow | create/rename/add/remove/reorder/note/section/query/freeze/compare |
| Static vs dynamic | explicit; manual membership wins; no silent change |
| Reconstruction | versions/email/archive/duplicates/timeline evidence packs |
| Search/timeline/graph → dossier | wired (search + graph UI actions, timeline service) |
| AI summary | optional, policy-aware, source-bounded, citation-grounded, labelled |
| Privacy modes | FULL_LOCAL/MASK_PII/OMIT_HIGH_SENSITIVITY/PATH_REDACTED/METADATA_ONLY |
| Redacted export | M015 redaction reused; original never modified |
| Manifest/reproducibility | checksums, source hashes, logical fingerprint; byte-PDF not claimed |
| UI | Dossiers & Reports page + search/graph actions |
| Report history | definitions + artifacts persisted; missing artifact handled |
| Output-dir safety | configurable, traversal-proof, collision-resistant, atomic |
| Real benchmark | `reports_m016.json`, `reports_m017.json`, `reports_m014.json` |
| PDF benchmark | `tests/integration/test_m018_pdf_quality.py` (FR/DE/EN, 200-row multi-page) |
| Dossier/reconstruction quality | 7 + 8 unit tests |
| Privacy hostile review | 11 tests |
| General hostile review | citation/path/overwrite/provider/history/summary cases |

## Hostile review — defects found and repaired

| # | Finding | Severity | Repair |
|---|---|---|---|
| 1 | No warning when a FULL_LOCAL report includes high-sensitivity documents | major | `_apply_privacy` now adds an explicit warning |
| 2 | Artifact filename could collide under concurrent generation | minor | always-unique random token in the name |
| 3 | `DossierService.list` shadowed the builtin and broke typing | minor | renamed `list_dossiers` |
| 4 | Missing optional tables (intel/versions) triggered noisy DB error-retry | minor | `has_table` guards |
| 5 | Unbounded renderer reads / provider temp dirs | minor | size caps, isolated profiles, validated output, cleanup |

## Regression gates

| Gate | Result | Note |
|---|---|---|
| audit | PASS | |
| compileall | PASS | |
| pytest | PASS | **594 collected**, 0 failed (5 AI skips) |
| `git diff --check` | PASS | |
| ruff | FAIL (baseline) | **6998 = baseline, 0 in M018 files** |
| mypy | FAIL (baseline) | **1137 / 65 files = baseline, 0 in M018 files** |

The red ruff/mypy gates are the long-standing repository-wide debt present in
every prior `.validation/` run. **M018 adds 0 new ruff/mypy findings.**

## Safety

* Production DB untouched by M018 (all tests use isolated temp DBs or the
  `/home/chu/.pis-trials/` copies; the empty repo default DB is only initialized
  by a pre-existing path-isolation test).
* Source corpus untouched (read-only).
* No export artifacts committed (all under `/home/chu/.pis-trials/` or temp).
* Local only; no push.

## Residual limitations

PDF byte-determinism not claimed; CSS page-number counters not guaranteed under
LibreOffice/Chrome; PST/OST remain unsupported (M017 dependency); PII masking is
the conservative M015 regex detector.
