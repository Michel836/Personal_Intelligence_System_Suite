# Local API, CLI, Maintenance, Backup/Restore & Vector Decision (M019)

M019 adds the operational interface and maintenance layer. It remains a
**mono-user, local-only** application: no multi-user auth, no RBAC, no cloud
control plane, no mandatory Redis/Celery/MinIO/PostgreSQL, and no destructive
migration without a rollback path.

New code: `src/ops/` (config, schema, doctor, health, maintenance, backup,
instance, pgvector), `src/api/` (Starlette REST), `src/cli.py` (`pis`), and the
**🧰 Operations & System** UI page. Benchmarks: `scripts/bench/m019_ops.py`.

## Local REST API

Built on **Starlette** (already present with uvicorn); FastAPI is *not* required.
Stable prefix `/api/v1`, every response carries `"schema": "api/v1"`.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1` | index + version |
| `GET /api/v1/health` | safe aggregate health |
| `GET /api/v1/doctor` | diagnostics (no secrets, no network probe) |
| `GET /api/v1/maintenance/status` | DB/FTS/vacuum status |
| `GET /api/v1/files` · `GET /api/v1/files/{id}` | metadata, bounded preview |
| `GET /api/v1/search?q&mode=lexical\|semantic\|rerank` | search + filters |
| `GET /api/v1/duplicates` · `GET /api/v1/versions/{id}` | dedup/version |
| `GET /api/v1/entities` · `GET /api/v1/categories` | intelligence filters |
| `GET /api/v1/timeline` · `GET /api/v1/graph/neighborhood/{id}` | graph |
| `GET /api/v1/ingestion/issues` | extraction queue |
| `GET/POST /api/v1/dossiers` · `.../{id}` · `.../{id}/documents` · `.../{id}/freeze` | dossiers |
| `GET/POST /api/v1/reports` · `GET /api/v1/reports/{id}` | build/list/generate |

### Bind & privacy rules

* **Loopback-only default** (`127.0.0.1:8600`). Binding a non-loopback host is
  refused unless `--allow-remote`, and prints a strong warning; real auth/TLS is
  explicitly **out of scope**.
* PII is **always masked** in the API; paths are redacted by default and only
  shown with an explicit `?show_paths=1` (local use).
* Bounded pagination (default 25, cap 100), request timeout (30 s), body cap
  (1 MiB), query length cap.
* No arbitrary SQL, no arbitrary filesystem read, no command execution, no
  source-mutation endpoint. Semantic/rerank degrade to `available:false` when
  the backend is unavailable.

## CLI

One canonical entry point: `python -m src.cli <command>` or the installed
`pis` console script (`[project.scripts] pis = "src.cli:main"`).

```
pis status | doctor [--deep]
pis scan <root> [--dry-run] [--limit N]
pis extract [--limit N] [--scope PREFIX] [--ocr] [--dry-run]
pis search "query" [--mode lexical|semantic|rerank] [--extension .pdf] ...
pis semantic-refresh [--limit N]
pis duplicates | intel | graph [--file-id ID --depth N] | ingest-issues | retry
pis dossier list|create|add|remove|freeze|compare ...
pis report list|build --kind SEARCH --title T [--dry-run] [--formats HTML,PDF]
pis maintenance <op> [--confirm] | backup [--out DIR]
pis restore <archive> [--verify-only] [--target-db PATH --force --confirm --semantic]
pis api [--host H --port P --allow-remote]
pis ui [profile] [--port P]
```

Safety: every command supports `--json`; the resolved database is shown in human
mode so a production and a trial target cannot be confused; expensive commands
have `--dry-run`; `maintenance vacuum` and `restore` require explicit
confirmation flags; `--limit` is bounded (cap 500).

## Doctor / diagnostics

`pis doctor` (or `GET /api/v1/doctor`) returns one of
**OK / WARN / ERROR / NOT_CONFIGURED** per check: DB readable/writable,
integrity (skipped on large DBs unless `--deep`), FTS consistency, semantic
store, schema compatibility, Ollama (short probe, disable with
`PIS_DOCTOR_PROBE_NETWORK=0`), OCR/Tesseract, archive tools, LibreOffice, PDF
provider, PST (always NOT_CONFIGURED — documented), export/backup dirs, disk and
temp space, permissions, privacy policy and API bind mode. Secrets are never
emitted.

## Maintenance

`src/ops/maintenance.py` exposes bounded, timed, reportable operations:
`integrity`, `analyze`, `optimize`, `checkpoint`, `vacuum` (+ `vacuum-precheck`),
`fts-consistency`, `fts-rebuild`, `prune-relations`, `prune-intel`,
`prune-artifacts`, `prune-audit`, `orphan-scan`, `semantic-consistency`,
`schema-init`, `status`.

* **VACUUM is never automatic**: it requires `confirm=True`, passes a free-space
  precheck and recommends a backup first. Routine upkeep uses `PRAGMA optimize`
  and `ANALYZE`.
* FTS consistency counts **indexed rows** via the FTS5 shadow `_docsize` table
  (external-content `COUNT(*)` reads the content table and cannot detect an
  unindexed row).
* Semantic consistency compares the matrix store count to embedded
  `semantic_state` rows.

## Backup / restore

* **Application-consistent**: the SQLite DB is snapshotted with the SQLite
  backup API (WAL-safe), plus the semantic matrix store and a **secret-redacted**
  config snapshot. The source corpus is **never** copied or modified.
* Every backup gets a **manifest** (schema, backup id, timestamp, app/commit,
  DB schema version, per-component checksums, included/excluded components,
  privacy note, warnings), stored inside the archive and as a sidecar.
* **Restore is conservative**: verify archive safety (no absolute/`..`/symlink
  members) and every checksum, check schema compatibility, extract to a staging
  directory, run `integrity_check`, refuse to overwrite unless `force`, keep a
  `.pre-restore` rollback copy, and support restore-to-new-location first.
  Restore never touches the source corpus.

## Configuration precedence

`explicit argument` → `process environment (PIS_*)` → `.env` (only read by the
legacy pydantic `Settings`) → `code default`. The launcher applies profile
defaults with `setdefault`, so an operator value always wins. `pis doctor` shows
the effective, secret-redacted config and the resolved source of each value.

## Process / instance lifecycle

`src/ops/instance.py` provides a PID lock with **stale-lock recovery** (a crashed
owner never blocks forever), read-only duplicate detection (it never kills
another process), and port-conflict detection. `python -m src.launcher
--single-instance` (or `PIS_SINGLE_INSTANCE=1`) refuses a second guarded launch
and warns when duplicate app processes are already present. The API runs in the
foreground with an explicit host/port and graceful shutdown (Ctrl-C).

## Schema & migrations

SQLite schema reporting uses `fts_meta.schema_version` plus `PRAGMA
user_version` (`src/ops/schema.py`). Migrations are **additive only**;
`pis maintenance schema-init` sets the user version and never drops a
column/table. The legacy Postgres/Alembic path is optional and unchanged.

## Vector backend decision (pgvector)

Decision: **KEEP_CURRENT / OPTIONAL_PGVECTOR**. Evidence: no reachable
PostgreSQL server (`PIS_PG_URL` unset); the NumPy matrix store remains the
canonical vector backend. `src/ops/pgvector.py` provides a backend abstraction
(`matrix` default, `pgvector` opt-in), a benchmark delegate
(`scripts/bench/bench_pgvector.py`), an evidence-based `decide()`, and migration
tooling (`migration_plan`, `export_to_pgvector` dry-run/resumable,
`rollback_pgvector`). pgvector, if enabled, backs **vectors only** — canonical
metadata and FTS stay in SQLite, and the backend falls back cleanly when
unavailable. The dead SQLAlchemy `core/postgres_database.py` is not used.

## Measured (M017 trial DB copy, `/home/chu/.pis-trials/m019/`)

Aggregate only; no filename, path or content recorded.

| Step | Result |
|---|---|
| DB copy (4.78 GB) | 11.4 s |
| integrity_check | **OK** (11.2 s) |
| analyze / optimize | 0.48 s / 0.0004 s |
| FTS consistency | 358,982 indexed = 358,982 files |
| semantic consistency | consistent |
| orphan scan | 0 |
| backup | 198 s, archive **1.51 GB**, verified |
| restore → staging | **RESTORED**, row counts identical |
| pgvector | unavailable (no server) → KEEP_CURRENT |

## Known limitations

* The API has **no authentication/TLS** by design; it is loopback-only and must
  not be exposed on a network. Remote/LAN use is out of scope.
* No automation/scheduling daemon and no WebSockets (deliberate).
* The SQLite/VACUUM path operates on the canonical DB; very large VACUUMs still
  require free space roughly equal to the DB size and a backup.
* pgvector is optional and unbenchmarked here (no server); adopting it at scale
  remains a future, evidence-gated decision.
