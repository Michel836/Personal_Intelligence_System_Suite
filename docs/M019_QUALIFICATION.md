# M019 Qualification Report — Local API, CLI, Maintenance, Backup/Restore

**Status:** QUALIFIED (local, bounded, evidence-backed)
**Branch:** `feat/m001-validation-harness` (no push)
**Base HEAD:** `d65e02e`
**Evidence:** the most recent `.validation/<UTC run>/` (its `validation.json`
binds the complete final state) and `/home/chu/.pis-trials/m019/evidence/`

## Scope

Operational layer: opt-in loopback REST API (Starlette), canonical `pis` CLI,
doctor/diagnostics, bounded maintenance, application-consistent backup/restore,
process/instance safety, config precedence, schema-version reporting, and an
evidence-based optional pgvector decision.

## Phases

| Phase | Result |
|---|---|
| Existing API/CLI/maintenance audit | done (see `docs/M019_OPERATIONS.md`) |
| API contract + safety + versioning | `/api/v1`, loopback-only, masked PII, bounded, no arbitrary I/O |
| Search API | lexical/semantic/rerank, filters, pagination, graceful degradation |
| Dossier/report API | create/add/freeze/detail; build (dry-run) + generate + manifest |
| CLI contract + commands | `pis` with 18 commands, `--json`, `--dry-run`, bounded limits |
| Doctor | OK/WARN/ERROR/NOT_CONFIGURED across DB/FTS/semantic/tools/policy/bind |
| Health endpoint | aggregate only; private paths only on explicit local request |
| Maintenance contract | integrity/analyze/optimize/checkpoint/vacuum-precheck/FTS/prune/consistency |
| Vacuum policy | never automatic; precheck + confirmation |
| Backup contract + manifest | SQLite backup API + semantic store + redacted config + checksums |
| Restore contract | verify → staging → integrity → rollback copy → atomic replace |
| Hostile backup/restore | truncated, wrong checksum, traversal, incompatible schema, corrupt DB, existing target, no secrets — all refused/detected |
| Config consolidation | explicit > env > dotenv > default; secrets redacted |
| Process/instance safety | PID lock + stale recovery + read-only duplicate detection |
| API lifecycle | foreground, explicit host/port, conflict detection, graceful shutdown |
| PostgreSQL audit | dead SQLAlchemy path identified; not used |
| pgvector benchmark | infeasible (no server) → recorded `available: false` |
| pgvector decision | **KEEP_CURRENT / OPTIONAL_PGVECTOR** (SQLite canonical) |
| Optional vector backend | abstraction + fallback + migration tooling |
| Migration tooling | `migration_plan`, dry-run export, count/dim validation, rollback |
| Schema/migrations | `fts_meta.schema_version` + `PRAGMA user_version`; additive only |
| API/CLI performance | bounded pagination/timeouts; batch rows ≤100 |
| Maintenance benchmark | integrity OK, backup 198 s / 1.51 GB, restore verified (§docs) |
| UI operations page | 🧰 Operations & System (health/doctor/maintenance/backup/API) |
| Logging/audit | action/component/duration/result; no PII/secrets/bodies |

## Hostile review — BLOCKER/MAJOR/MINOR

| # | Attack | Result | Class |
|---|---|---|---|
| 1 | API binds 0.0.0.0 silently | refused unless `--allow-remote`; strong warning | MAJOR (fixed) |
| 2 | API returns raw PII | always masked; no opt-out | BLOCKER prevented |
| 3 | arbitrary path fetch | no filesystem-read endpoint; 404/invalid id | BLOCKER prevented |
| 4 | unbounded search | limit capped at 100 | MAJOR (fixed) |
| 5 | SQL/command injection | canonical parameterized methods; no exec endpoint | BLOCKER prevented |
| 6 | backup captures inconsistent DB | SQLite backup API (WAL-safe) | MAJOR (fixed by design) |
| 7 | restore overwrites silently | refuses unless `force`; rollback copy | BLOCKER prevented |
| 8 | path traversal backup | member validation rejects `..`/absolute/symlink | MAJOR (fixed) |
| 9 | duplicate launch storm | PID lock + stale recovery + detector | MAJOR (fixed) |
| 10 | stale PID blocks forever | dead-owner lock reclaimed | MAJOR (fixed) |
| 11 | doctor leaks secrets | redacted config; test asserts no secret | MAJOR (fixed) |
| 12 | VACUUM fills disk | precheck + explicit confirm | MAJOR (fixed) |
| 13 | FTS rebuild loses rows | shadow `_docsize` consistency check + rebuild verify | MAJOR (fixed) |
| 14 | semantic check falsely passes | compares store count to embedded rows | MINOR |
| 15 | pgvector migration count mismatch | plan/validation + rollback (server-gated) | MINOR |

0 open BLOCKER/MAJOR.

## Regression gates

| Gate | Result | Note |
|---|---|---|
| pytest | PASS | **653 collected**, 0 failed (5 AI skips) |
| audit / compileall / diff-check | PASS | |
| ruff | FAIL (baseline) | **6998 = baseline, 0 new** |
| mypy | FAIL (baseline) | **1135 ≤ baseline 1137, 0 new** |

## Safety

* Production DB untouched (all tests/tools use isolated temp or `/home/chu/.pis-trials` copies).
* Source corpus untouched; backups never include it.
* No backup archives / trial DBs / secrets committed (all under trial dirs, gitignored).
* Local only; no push.

## Residual limitations

API has no auth/TLS (loopback-only by design); no automation/WebSockets; large
VACUUMs need ~DB-size free space; pgvector remains optional and unbenchmarked
(no server).
