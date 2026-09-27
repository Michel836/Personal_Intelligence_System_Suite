"""Galaxy/cluster/topic/context CLI integration tests (M020)."""
from __future__ import annotations

import json

import pytest

from src.cli import main


@pytest.fixture()
def cli_env(galaxy_env, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("PIS_EMBEDDING_STORE_DIR", str(galaxy_env.base_dir))
    return str(galaxy_env.db.db_path)


def test_cli_galaxy_json(cli_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--db", cli_env, "--json", "galaxy", "--scope", "all",
                 "--k", "5", "--limit", "50", "--method", "pca"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] is True
    assert payload["points"]


def test_cli_clusters_build_and_topics(cli_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--db", cli_env, "--json", "clusters", "--build", "--scope", "all",
                 "--k", "5"]) == 0
    clusters = json.loads(capsys.readouterr().out)
    assert clusters["available"] is True and clusters["run_id"]
    assert main(["--db", cli_env, "--json", "topics"]) == 0
    topics = json.loads(capsys.readouterr().out)
    assert topics["topics"]
    assert all(topic["label"] for topic in topics["topics"])


def test_cli_context(cli_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--db", cli_env, "--json", "context", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["document"]["id"] == 1
    assert payload["privacy"]["raw_pii_exposed"] is False


def test_cli_galaxy_human_output(cli_env: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--db", cli_env, "galaxy", "--scope", "all", "--k", "5", "--limit", "20"]) == 0
    out = capsys.readouterr().out
    assert "galaxy scope=all" in out
