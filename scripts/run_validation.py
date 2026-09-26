#!/usr/bin/env python3
"""Run reproducible validation gates and persist evidence.

Inspired by the validation harness used on Trajectory-OS/YTKC. Each command gets
its own stdout/stderr log plus a machine-readable summary. No user-data scan is
performed by this harness.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(os.environ.get("PYTHON_BIN", ROOT / ".venv" / "bin" / "python"))
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.strip()


def run(name: str, command: list[str], evidence_dir: Path) -> dict[str, object]:
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    (evidence_dir / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (evidence_dir / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return {"name": name, "command": command, "returncode": proc.returncode, "passed": proc.returncode == 0}


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = ROOT / ".validation" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=True)

    gates = [
        ("audit", [str(PYTHON), "scripts/audit_repo.py"]),
        ("compileall", [str(PYTHON), "-m", "compileall", "-q", "src", "scripts", "tests"]),
        ("ruff", [str(PYTHON), "-m", "ruff", "check", "src", "scripts", "tests"]),
        ("mypy", [str(PYTHON), "-m", "mypy", "src"]),
        ("pytest", [str(PYTHON), "-m", "pytest", "-q"]),
        ("diff_check", ["git", "diff", "--check"]),
    ]
    results = [run(name, command, evidence_dir) for name, command in gates]

    patch = subprocess.run(["git", "diff", "--binary", "main...HEAD"], cwd=ROOT, capture_output=True).stdout
    patch_sha256 = hashlib.sha256(patch).hexdigest()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "base_main": git("rev-parse", "main"),
        "worktree_status": git("status", "--porcelain"),
        "patch_sha256": patch_sha256,
        "python": str(PYTHON),
        "gates": results,
        "passed": all(bool(item["passed"]) for item in results),
    }
    (evidence_dir / "validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (evidence_dir / "validation.txt").write_text(
        "\n".join([f"{r['name']}: {'PASS' if r['passed'] else 'FAIL'} ({r['returncode']})" for r in results]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
