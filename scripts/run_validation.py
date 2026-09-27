#!/usr/bin/env python3
"""Run reproducible validation gates and persist evidence.

Inspired by the validation harness used on Trajectory-OS/YTKC. Each command gets
its own stdout/stderr log plus a machine-readable summary. No user-data scan is
performed by this harness.

Evidence integrity
------------------
The recorded ``validated_state_sha256`` is a deterministic fingerprint of the
complete validated repository state:

* ``committed_patch_sha256`` -- SHA-256 of ``git diff --binary main...HEAD``;
* ``working_tree_sha256`` -- SHA-256 over a sorted content manifest of every
  tracked file plus every untracked-but-not-ignored file;
* ``validated_state_sha256`` -- SHA-256 binding base commit, HEAD, the committed
  patch and the working-tree manifest together.

Because the working-tree manifest is built with ``git ls-files`` and
``git ls-files --others --exclude-standard``, ignored paths (``.git/``,
``.venv/``, ``.validation/``, caches, bytecode, runtime data) never contribute to
the fingerprint, while staged, unstaged and untracked relevant changes do.
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

# Defensive exclusions applied on top of ``.gitignore`` so the fingerprint never
# depends on the environment, caches or previous evidence.
_EXCLUDED_TOP_LEVEL = {".git", ".venv", ".validation"}
_HASH_CHUNK = 1 << 20
_MISSING = "<missing>"
_STATE_SCHEMA = "validation-state/v1"


def git(*args: str, cwd: Path = ROOT) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=False
    )
    return proc.stdout.strip()


def git_bytes(*args: str, cwd: Path = ROOT) -> bytes:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    return proc.stdout


def _validated_paths(cwd: Path = ROOT) -> list[str]:
    """Sorted repo-relative paths that make up the validated repository state."""
    tracked = git_bytes("ls-files", "-z", cwd=cwd).split(b"\0")
    untracked = git_bytes(
        "ls-files", "--others", "--exclude-standard", "-z", cwd=cwd
    ).split(b"\0")
    paths: set[str] = set()
    for raw in (*tracked, *untracked):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        if rel.split("/", 1)[0] in _EXCLUDED_TOP_LEVEL:
            continue
        paths.add(rel)
    return sorted(paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_manifest(cwd: Path = ROOT) -> list[dict[str, str]]:
    """Path -> content-hash manifest of the validated working tree."""
    manifest: list[dict[str, str]] = []
    for rel in _validated_paths(cwd):
        full = cwd / rel
        entry_sha = _sha256_file(full) if full.is_file() else _MISSING
        manifest.append({"path": rel, "sha256": entry_sha})
    return manifest


def working_tree_sha256(cwd: Path = ROOT) -> str:
    """Deterministic hash over the validated file manifest."""
    digest = hashlib.sha256()
    for entry in validated_manifest(cwd):
        digest.update(entry["path"].encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def committed_patch_sha256(cwd: Path = ROOT) -> str:
    """SHA-256 of the committed branch delta between ``main`` and ``HEAD``."""
    base_main = git("rev-parse", "--verify", "main", cwd=cwd)
    patch = git_bytes("diff", "--binary", "main...HEAD", cwd=cwd) if base_main else b""
    return hashlib.sha256(patch).hexdigest()


def tree_state(cwd: Path = ROOT) -> str:
    """``CLEAN`` when there are no staged, unstaged or untracked changes."""
    return "DIRTY" if git("status", "--porcelain", cwd=cwd) else "CLEAN"


def fingerprint(cwd: Path = ROOT) -> dict[str, str]:
    """Return the committed and working-tree digests for a repository state."""
    base_main = git("rev-parse", "--verify", "main", cwd=cwd)
    head = git("rev-parse", "HEAD", cwd=cwd)
    committed_sha = committed_patch_sha256(cwd)
    working_sha = working_tree_sha256(cwd)
    payload = {
        "schema": _STATE_SCHEMA,
        "base_main": base_main,
        "head": head,
        "committed_patch_sha256": committed_sha,
        "working_tree_sha256": working_sha,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "base_main": base_main,
        "head": head,
        "committed_patch_sha256": committed_sha,
        "working_tree_sha256": working_sha,
        "validated_state_sha256": hashlib.sha256(blob).hexdigest(),
    }


def validated_state_sha256(cwd: Path = ROOT) -> str:
    """SHA-256 binding committed delta and working tree into one fingerprint."""
    return fingerprint(cwd)["validated_state_sha256"]


def run(name: str, command: list[str], evidence_dir: Path) -> dict[str, object]:
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    (evidence_dir / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (evidence_dir / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return {"name": name, "command": command, "returncode": proc.returncode, "passed": proc.returncode == 0}


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = ROOT / ".validation" / stamp
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot the exact state that is about to be validated.
    before = fingerprint(ROOT)

    gates = [
        ("audit", [str(PYTHON), "scripts/audit_repo.py"]),
        ("compileall", [str(PYTHON), "-m", "compileall", "-q", "src", "scripts", "tests"]),
        ("ruff", [str(PYTHON), "-m", "ruff", "check", "src", "scripts", "tests"]),
        ("mypy", [str(PYTHON), "-m", "mypy", "src"]),
        ("pytest", [str(PYTHON), "-m", "pytest", "-q"]),
        ("diff_check", ["git", "diff", "--check"]),
    ]
    results = [run(name, command, evidence_dir) for name, command in gates]

    # The gates must not mutate the validated state; record and flag any drift.
    after = fingerprint(ROOT)
    worktree_status = git("status", "--porcelain")
    summary = {
        "schema": "validation-evidence/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": git("branch", "--show-current"),
        "head": before["head"],
        "base_main": before["base_main"],
        "worktree_status": worktree_status,
        "tree_state": "DIRTY" if worktree_status else "CLEAN",
        "committed_patch_sha256": before["committed_patch_sha256"],
        "working_tree_sha256": before["working_tree_sha256"],
        "validated_state_sha256": before["validated_state_sha256"],
        "post_validation_state_sha256": after["validated_state_sha256"],
        "state_stable_during_gates": after["validated_state_sha256"] == before["validated_state_sha256"],
        "validated_file_count": len(_validated_paths(ROOT)),
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
