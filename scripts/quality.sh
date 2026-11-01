#!/usr/bin/env bash
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-./.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

FAIL=0
run_gate() {
  local name="$1"; shift
  printf '\n==> %s\n' "$name"
  if "$@"; then
    printf '[PASS] %s\n' "$name"
  else
    printf '[FAIL] %s\n' "$name"
    FAIL=1
  fi
}

run_gate "audit" "$PYTHON_BIN" scripts/audit_repo.py
run_gate "compileall" "$PYTHON_BIN" -m compileall -q src scripts tests
run_gate "quality gate (ruff+mypy budget)" "$PYTHON_BIN" scripts/quality_gate.py
run_gate "pytest" "$PYTHON_BIN" -m pytest -q
run_gate "git diff --check" git diff --check

exit "$FAIL"
