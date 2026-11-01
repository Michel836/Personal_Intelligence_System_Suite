# New-User Acceptance — fresh venv, wheel, real value loop (M022)

This is the "would a non-developer get value?" gate. It is implemented as an
executable script:

```bash
scripts/acceptance_new_user.sh          # full run, cleans up
scripts/acceptance_new_user.sh --keep   # keep the temp dir for inspection
```

The script:

1. builds the wheel from the checkout (`python -m pip wheel . --no-deps`);
2. creates a **fresh virtualenv** and installs only that wheel (pip resolves the
   declared core dependencies);
3. runs `pip check`;
4. creates an isolated `PIS_DATA_DIR` / `PIS_EXPORT_DIR` and a small corpus;
5. exercises the canonical loop with the installed `pis` binary:
   `--help`, `status`, `scan`, `extract`, `search`, `report build`, `doctor`,
   `embed --status`, `--json status`;
6. asserts the MVP contracts:
   * no CWD-relative `./data` is created (XDG/`PIS_DATA_DIR` only);
   * a corpus with an unreadable subtree ends `COMPLETED_WITH_WARNINGS`
     (exit **3**) and still indexes the readable part;
   * `--strict` fails closed (exit **2**).

## Last recorded result

**Date:** 2026-11-01 · **Host:** Linux, Python 3.11.15, RTX 3090
**Wheel:** `36tb_intelligence-1.0.0rc1-py3-none-any.whl`

```
== Result ==
  passed: 20
  failed: 0
  NEW-USER ACCEPTANCE: PASS
```

Covered checks (all PASS):

| Check | Result |
|---|---|
| Wheel build + clean-venv install | PASS |
| `pip check` (no broken requirements) | PASS |
| `pis --help`, `status`, `doctor` | PASS |
| `scan` completes the corpus | PASS |
| `extract` reports `EXTRACTED` | PASS |
| `search` returns the document | PASS |
| `report build --formats html,json` produces 2 artefacts + manifest on disk | PASS |
| `embed --status` works without an AI extra | PASS |
| `--json status` exposes `_meta.db` / coverage | PASS |
| No CWD-relative `./data` created | PASS |
| Safe partial scan → `COMPLETED_WITH_WARNINGS`, exit 3 | PASS |
| Strict scan → `FAILED`, exit 2 | PASS |

## Manual equivalent

```bash
python -m pip wheel . --no-deps -w dist
python -m venv /tmp/pis-wheel && /tmp/pis-wheel/bin/pip install dist/*.whl
/tmp/pis-wheel/bin/pip check

export PIS_DATA_DIR=/tmp/pis-data PIS_EXPORT_DIR=/tmp/pis-exports
/tmp/pis-wheel/bin/pis scan ~/Documents
/tmp/pis-wheel/bin/pis extract --limit 500
/tmp/pis-wheel/bin/pis search facture
/tmp/pis-wheel/bin/pis report build --kind SEARCH \
  --query '{"query":"facture"}' --formats HTML,JSON
```

## Notes

* The wheel declares **22 core runtime dependencies** and optional extras
  (`ai`, `ocr`, `docs`, `cloud`, `postgres`, `mcp`, `dev`). A core-only install
  deliberately has no `torch`/`sentence-transformers`; `pis embed --status`
  still works and reports `NOT_CONFIGURED` with an install hint when the `ai`
  extra is absent.
* The test needs network access only to resolve the wheel's dependencies (or a
  populated pip cache). The application itself never contacts a remote service
  (`PIS_REMOTE_CONTENT_POLICY=never`).
* CI runs the same flow in `.github/workflows/quality.yml` (`wheel` job).
