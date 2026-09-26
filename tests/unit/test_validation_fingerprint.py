"""Regression tests for ``scripts/run_validation.py`` evidence integrity.

The validation fingerprint must be bound to the complete validated repository
state while ignoring environment, cache and evidence paths. These tests build
isolated temporary git repositories and never mutate the real repository.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
_RUN_VALIDATION_PATH = ROOT / "scripts" / "run_validation.py"


def _load_run_validation() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_validation", _RUN_VALIDATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Validation Tests")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".gitignore").write_text(
        ".validation/\n.venv/\n__pycache__/\ndata/\n*.log\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_clean_worktree_hash_is_stable(repo: Path) -> None:
    mod = _load_run_validation()

    assert mod.tree_state(repo) == "CLEAN"
    assert mod.working_tree_sha256(repo) == mod.working_tree_sha256(repo)
    assert mod.validated_state_sha256(repo) == mod.validated_state_sha256(repo)


def test_editing_tracked_file_changes_validated_state(repo: Path) -> None:
    mod = _load_run_validation()
    before = mod.validated_state_sha256(repo)

    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")

    assert mod.validated_state_sha256(repo) != before
    assert mod.tree_state(repo) == "DIRTY"


def test_staged_change_changes_validated_state(repo: Path) -> None:
    mod = _load_run_validation()
    before = mod.validated_state_sha256(repo)

    (repo / "src" / "app.py").write_text("print('staged')\n", encoding="utf-8")
    _git(repo, "add", "src/app.py")

    assert mod.validated_state_sha256(repo) != before


def test_untracked_relevant_file_changes_validated_state(repo: Path) -> None:
    mod = _load_run_validation()
    before = mod.validated_state_sha256(repo)

    (repo / "src" / "new_module.py").write_text("x = 1\n", encoding="utf-8")

    assert mod.validated_state_sha256(repo) != before


def test_validation_dir_is_excluded(repo: Path) -> None:
    mod = _load_run_validation()
    before = mod.validated_state_sha256(repo)

    evidence = repo / ".validation" / "20260101T000000Z"
    evidence.mkdir(parents=True)
    (evidence / "validation.json").write_text('{"seed": true}\n', encoding="utf-8")

    assert mod.validated_state_sha256(repo) == before


def test_git_ignored_files_are_excluded(repo: Path) -> None:
    mod = _load_run_validation()
    before = mod.validated_state_sha256(repo)

    (repo / "debug.log").write_text("noise\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "cache.bin").write_bytes(b"\x00\x01\x02")

    assert mod.validated_state_sha256(repo) == before
