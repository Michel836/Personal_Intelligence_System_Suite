#!/usr/bin/env bash
# New-user acceptance test (Week 4, point 11).
#
# Proves that a *fresh* environment can install the wheel and complete the core
# value loop without a developer shell:
#
#   venv -> install wheel -> scan -> extract -> search -> report -> doctor
#
# It also checks the MVP hardening contracts: XDG data paths (no ./data in the
# CWD), CLI exit codes, and safe partial scans (when run as a non-root user).
#
# Usage:
#   scripts/acceptance_new_user.sh            # full run, cleans up
#   scripts/acceptance_new_user.sh --keep     # keep the temp dir and print it
#   scripts/acceptance_new_user.sh --wheel P  # use an existing wheel
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP=0
WHEEL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1 ;;
        --wheel) WHEEL="$2"; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    PYTHON="$(command -v python3.11 || command -v python)"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/pis-acceptance-XXXXXX")"
cleanup() {
    if [ "$KEEP" = "1" ]; then
        echo "kept: $WORK"
    else
        rm -rf "$WORK"
    fi
}
trap cleanup EXIT

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check() { # check <description> <command...>
    local description="$1"; shift
    local status=0
    "$@" >"$WORK/last.out" 2>"$WORK/last.err" || status=$?
    if [ "$status" -eq 0 ]; then
        pass "$description"
    else
        fail "$description (exit $status)"
        tail -20 "$WORK/last.err" | sed 's/^/       /'
    fi
}

echo "== 1. Build / select the wheel =="
if [ -z "$WHEEL" ]; then
    "$PYTHON" -m pip wheel "$ROOT" --no-deps -w "$WORK/dist" >"$WORK/build.log" 2>&1 \
        || { tail -30 "$WORK/build.log"; exit 1; }
    WHEEL="$(ls "$WORK"/dist/*.whl | head -1)"
fi
[ -f "$WHEEL" ] || { echo "wheel not found: $WHEEL" >&2; exit 1; }
pass "wheel available: $(basename "$WHEEL")"

echo "== 2. Create a clean virtualenv and install the wheel =="
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --quiet --upgrade pip
if "$WORK/venv/bin/pip" install --quiet "$WHEEL" >"$WORK/install.log" 2>&1; then
    pass "wheel installed (core dependencies resolved by pip)"
else
    fail "wheel installation"
    tail -30 "$WORK/install.log"
    exit 1
fi
check "pip check reports no broken requirements" "$WORK/venv/bin/pip" check

echo "== 3. Prepare an isolated run (XDG data, no ./data in CWD) =="
mkdir -p "$WORK/corpus" "$WORK/cwd"
printf 'Facture ACME total 1250 EUR. Contact jean.dupont@example.com\n' > "$WORK/corpus/facture.txt"
printf '# Notes\nProjet Alpha migration des donnees\n' > "$WORK/corpus/notes.md"
printf 'alpha,beta,gamma\n1,2,3\n' > "$WORK/corpus/data.csv"
cat > "$WORK/env.sh" <<EOF
export PIS_DATA_DIR="$WORK/data"
export PIS_EXPORT_DIR="$WORK/exports"
export PIS_NO_AUTO_MIGRATE=1
unset PIS_DB_PATH
EOF
# shellcheck disable=SC1091
. "$WORK/env.sh"
PIS="$WORK/venv/bin/pis"
cd "$WORK/cwd"

echo "== 4. Core value loop =="
check "pis --help" "$PIS" --help
check "pis status" "$PIS" status
check "pis scan (complete corpus)" "$PIS" scan "$WORK/corpus"
grep -q "scan COMPLETED" "$WORK/last.out" \
    && pass "scan reported COMPLETED" || fail "scan did not report COMPLETED"
check "pis extract" "$PIS" extract --limit 20
grep -q "EXTRACTED" "$WORK/last.out" \
    && pass "extraction reported EXTRACTED" || fail "extraction did not report EXTRACTED"
check "pis search (lexical)" "$PIS" search facture
grep -q "facture.txt" "$WORK/last.out" \
    && pass "search returned the document" || fail "search did not return the document"
check "pis report build (lowercase formats)" "$PIS" report build \
    --kind SEARCH --query '{"query":"facture"}' --formats html,json
grep -q "report generated: 2 artifact" "$WORK/last.out" \
    && pass "report produced HTML + JSON" || fail "report artifacts missing"
ls "$WORK"/exports/*.html >/dev/null 2>&1 \
    && pass "HTML artifact exists on disk" || fail "HTML artifact missing on disk"
check "pis doctor" "$PIS" doctor
check "pis embed --status" "$PIS" embed --status
check "pis --json status exposes _meta" bash -c \
    "'$PIS' --json status | grep -q '\"_meta\"'"

echo "== 5. MVP contracts =="
if [ -d "$WORK/cwd/data" ]; then
    fail "CWD-relative ./data was created (must use XDG/PIS_DATA_DIR)"
else
    pass "no CWD-relative ./data directory"
fi

if [ "$(id -u)" != "0" ]; then
    mkdir -p "$WORK/partial/ok" "$WORK/partial/locked"
    printf 'ok\n' > "$WORK/partial/ok/a.txt"
    printf 'secret\n' > "$WORK/partial/locked/b.txt"
    chmod 000 "$WORK/partial/locked"
    set +e
    "$PIS" scan "$WORK/partial" >"$WORK/partial.out" 2>"$WORK/partial.err"
    code=$?
    set -e
    if [ "$code" = "3" ] && grep -q "COMPLETED_WITH_WARNINGS" "$WORK/partial.out"; then
        pass "safe partial scan -> COMPLETED_WITH_WARNINGS (exit 3)"
    else
        fail "safe partial scan (exit $code)"
        cat "$WORK/partial.out" "$WORK/partial.err"
    fi
    set +e
    "$PIS" scan "$WORK/partial" --strict >"$WORK/strict.out" 2>"$WORK/strict.err"
    code=$?
    set -e
    chmod 755 "$WORK/partial/locked"
    if [ "$code" = "2" ]; then
        pass "strict scan fails closed (exit 2)"
    else
        fail "strict scan exit code ($code)"
    fi
else
    echo "  SKIP partial-scan checks (running as root)"
fi

echo
echo "== Result =="
echo "  passed: $PASS"
echo "  failed: $FAIL"
if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
echo "  NEW-USER ACCEPTANCE: PASS"
