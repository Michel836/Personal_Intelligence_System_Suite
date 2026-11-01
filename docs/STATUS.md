# 36TB Intelligence — System Status

**Version:** `1.0.0rc2` · **Status:** functional MVP (Linux, mono-user, local-first)
**Last validated:** 2026-11-01

## Where the project stands

| Area | State |
|---|---|
| Core engine (scan, SQLite/FTS, extraction, ops) | ✅ MVP-ready |
| Intelligence (intel, duplicates, graph, reports, galaxy) | ✅ Implemented and tested; real-corpus evidence in [`REAL_CORPUS.md`](REAL_CORPUS.md) |
| CLI / API / backup / doctor | ✅ MVP-ready |
| UI (one canonical Streamlit app, 20 pages) | ✅ Functional; legacy Modern UI removed |
| Packaging / install | ✅ Wheel + constrained install validated on a clean venv |
| Quality gates | ✅ Budgeted ruff/mypy gate (no regressions; ratcheting) |
| Real 36 TB scale | ⚠️ Not yet demonstrated (15k files / 614 embedded docs validated) |

## Canonical surfaces (there is only one of each)

* **App:** `src/ui/app.py`, launched with `python -m src.launcher --profile lite|smart|full`
* **CLI:** `pis` (`status`, `scan`, `extract`, `search`, `embed`, `hashes`, `derived`, `report`, `backup`, …)
* **API:** loopback only (`pis api`, `http://127.0.0.1:8600/api/v1`)
* **Database:** SQLite at `~/.local/share/pis/indexes/files.db` (override with `PIS_DB_PATH`)
* **Vector store:** NumPy matrix at `~/.local/share/pis/cache/embeddings`
* **Exports / backups:** `~/.pis-exports` / `~/.pis-backups`

## Quick verification

```bash
pis status                 # files, semantic coverage, policy, resolved DB
pis doctor                 # actionable diagnostics
pis embed --status         # resumable embedding job + coverage
python scripts/quality_gate.py
python -m pytest -q
```

## Known limits

* Linux-first; Windows/macOS not part of the validated MVP.
* 36 TB / multi-million-document scale is designed for but not yet measured.
* PST/OST need external tools; OCR is opt-in.
* PostgreSQL/pgvector is optional and unexercised.
* Mono-user: the loopback API has no auth/TLS.

## Documentation

* [`RELEASE_NOTES.md`](RELEASE_NOTES.md) — capabilities and known limitations
* [`RELEASE_CANDIDATE.md`](RELEASE_CANDIDATE.md) — install and operate
* [`REAL_CORPUS.md`](REAL_CORPUS.md) — instrumented real-corpus run
* [`ACCEPTANCE_NEW_USER.md`](ACCEPTANCE_NEW_USER.md) — fresh-install acceptance
* [`VALIDATION_PROTOCOL.md`](VALIDATION_PROTOCOL.md) — quality gates
* [`history/`](history/) — superseded documents (traceability only)
