"""Release CLI + live loopback API acceptance (M021)."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from src.api import API_SCHEMA, bind_warning, create_app  # noqa: E402
from src.cli import main as cli_main  # noqa: E402


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict | str]:
    code = cli_main(argv)
    out = capsys.readouterr().out.strip()
    try:
        return code, json.loads(out)
    except json.JSONDecodeError:
        return code, out


def _db_args(release_env) -> list[str]:
    return ["--db", str(release_env.db.db_path), "--json"]


def test_cli_release_surface(release_env, capsys, tmp_path) -> None:
    env = release_env
    db = _db_args(env)

    code, status = _run(capsys, [*db, "status"])
    assert code == 0 and status["db"]["files_total"] >= 20
    code, doctor = _run(capsys, [*db, "doctor"])
    assert code == 0 and doctor["status"] in {"OK", "WARN", "ERROR", "DEGRADED"}

    code, dry = _run(capsys, [*db, "scan", str(env.corpus.root), "--dry-run"])
    assert code == 0 and dry["dry_run"] is True

    code, found = _run(capsys, [*db, "search", "finance", "--limit", "5"])
    assert code == 0 and found["count"] >= 1
    code, search_json = _run(capsys, [*db, "search", "finance"])
    assert search_json["available"] is True

    assert _run(capsys, [*db, "duplicates"])[0] == 0
    assert _run(capsys, [*db, "intel", "--limit", "30"])[0] == 0
    assert _run(capsys, [*db, "graph", "--min-docs", "1"])[0] == 0
    assert _run(capsys, [*db, "ingest-issues", "--limit", "30"])[0] == 0
    assert _run(capsys, [*db, "maintenance", "list"])[0] == 0

    fid = env.file_id("docs/alpha_finance.txt")
    assert _run(capsys, [*db, "graph", "--file-id", str(fid)])[0] == 0

    code, dossier = _run(capsys, [*db, "dossier", "create", "--name", "CLI dossier",
                                  "--doc-ids", str(fid)])
    assert code == 0 and dossier["dossier_id"]
    code, report = _run(capsys, [*db, "report", "build", "--kind", "SEARCH", "--title",
                                 "CLI report", "--query", '{"query": "finance"}',
                                 "--formats", "HTML,JSON", "--dry-run"])
    assert code == 0 and report["logical_fingerprint"]

    code, backup = _run(capsys, [*db, "backup", "--out", str(tmp_path / "backups")])
    assert code == 0 and Path(backup["archive_path"]).exists()
    code, verify = _run(capsys, [*db, "restore", backup["archive_path"], "--verify-only"])
    assert code == 0 and verify["ok"] is True

    assert _run(capsys, [*db, "galaxy", "--scope", "all", "--k", "4", "--limit", "50"])[0] == 0
    assert _run(capsys, [*db, "clusters", "--build", "--scope", "all", "--k", "4"])[0] == 0
    assert _run(capsys, [*db, "topics"])[0] == 0


def test_cli_wrong_arguments_and_db_protection(release_env, capsys, tmp_path) -> None:
    env = release_env
    with pytest.raises(SystemExit):
        cli_main(["galaxy", "--method", "bogus"])
    with pytest.raises(SystemExit):
        cli_main([])
    # Restore without confirmation is refused (not silently applied).
    code, backup = _run(capsys, [*_db_args(env), "backup", "--out", str(tmp_path / "b")])
    target = tmp_path / "should-not-exist.db"
    code, refused = _run(capsys, [*_db_args(env), "restore", backup["archive_path"],
                                  "--target-db", str(target)])
    assert refused["status"] == "REFUSED"
    assert not target.exists()


# --- API: in-process --------------------------------------------------------
@pytest.fixture()
def api_client(release_env) -> TestClient:
    return TestClient(create_app(release_env.db))


def test_api_endpoints_and_masking(api_client: TestClient, release_env) -> None:
    assert api_client.get("/api/v1").json()["schema"] == API_SCHEMA
    assert api_client.get("/api/v1/health").status_code == 200
    assert api_client.get("/api/v1/files?limit=5").status_code == 200
    assert api_client.get("/api/v1/search?q=finance").status_code == 200
    assert api_client.get("/api/v1/timeline?limit=5").status_code == 200
    assert api_client.get("/api/v1/ingestion/issues").status_code == 200
    assert api_client.get("/api/v1/duplicates").status_code == 200
    assert api_client.get("/api/v1/dossiers").status_code == 200
    assert api_client.get("/api/v1/reports").status_code == 200
    assert api_client.get("/api/v1/galaxy?scope=all&k=4&limit=50").status_code == 200

    files = api_client.get("/api/v1/files?limit=10")
    assert all(d["path"].startswith("<redacted>/") for d in files.json()["data"])
    assert "/tmp/" not in files.text

    fid = release_env.file_id("docs/alpha_finance.txt")
    assert api_client.get(f"/api/v1/context/{fid}").status_code == 200
    assert api_client.get("/api/v1/clusters").status_code == 200
    assert api_client.get("/api/v1/topics").status_code == 200


def test_api_bind_is_loopback_only_by_default() -> None:
    assert bind_warning("127.0.0.1") is None
    assert bind_warning("::1") is None
    warning = bind_warning("0.0.0.0")
    assert warning and "WARNING" in warning and "auth" in warning.lower()


def test_live_loopback_api_process_starts_and_stops(release_env) -> None:
    import socket
    import subprocess
    import sys

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    env = {
        "PIS_DB_PATH": str(release_env.db.db_path),
        "PIS_EMBEDDING_STORE_DIR": str(release_env.store_dir),
        "PIS_REMOTE_CONTENT_POLICY": "never",
        "PIS_DOCTOR_PROBE_NETWORK": "0",
    }
    import os
    child_env = {**os.environ, **env}
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from src.api.app import main; raise SystemExit(main(['--port', '" + str(port) + "']))"],
        cwd=str(root), env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        body = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as resp:
                    body = json.loads(resp.read().decode())
                    break
            except Exception:  # noqa: BLE001 - still starting
                time.sleep(0.3)
        assert body is not None, "API did not become reachable on loopback"
        assert body["schema"] == API_SCHEMA
        assert body["data"]["status"] in {"OK", "DEGRADED", "WARN"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    # Port is released after a clean shutdown (SO_REUSEADDR probe).
    from src.launcher import port_available
    deadline = time.time() + 15
    while time.time() < deadline:
        if port_available("127.0.0.1", port):
            break
        time.sleep(0.2)
    else:  # pragma: no cover - only on a stuck process
        pytest.fail("API port was not released after shutdown")
