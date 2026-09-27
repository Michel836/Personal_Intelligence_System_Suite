#!/usr/bin/env bash
# Launch the canonical app with the LITE profile (M012-B2).
# Linux / Kubuntu / macOS. Pass-through args, e.g. `run_lite.sh --port 9000`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    PY="$(command -v python3 || command -v python)"
fi

cd "$ROOT"
exec "$PY" -m src.launcher --profile lite "$@"
