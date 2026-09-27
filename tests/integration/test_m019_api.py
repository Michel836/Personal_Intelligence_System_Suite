"""Local REST API integration + safety (M019)."""
from __future__ import annotations

import pytest

pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from src.api import API_SCHEMA, API_VERSION, bind_warning, create_app  # noqa: E402
from src.core.database import DatabaseManager  # noqa: E402

PII_EMAIL = "jean.dupont@example.com"


@pytest.fixture()
def client(tmp_path) -> TestClient:
    db = DatabaseManager(tmp_path / "files.db")
    with db.get_connection() as conn:
        for i in (1, 2, 3):
            conn.execute(
                "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
                "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 10, "
                "'2024-01-01', 'ACTIVE', 'PHYSICAL_FILE', 1)",
                (i, f"/private/dir/{i}.txt", f"{i}.txt"))
        conn.commit()
    db.update_content(1, f"cancer note, contact {PII_EMAIL}")
    db.update_content(2, "resume candidat")
    return TestClient(create_app(db))


def test_index_reports_schema_version(client: TestClient) -> None:
    resp = client.get("/api/v1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema"] == API_SCHEMA
    assert body["data"]["api_version"] == API_VERSION


def test_health_is_aggregate_without_private_paths(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "/private/dir" not in resp.text
    assert resp.json()["data"]["db"]["files_total"] == 3


def test_files_masks_paths_and_paginates(client: TestClient) -> None:
    resp = client.get("/api/v1/files?limit=2")
    data = resp.json()["data"]
    assert len(data) == 2
    assert all(d["path"].startswith("<redacted>/") for d in data)
    assert "/private/dir" not in resp.text
    page = resp.json()["page"]
    assert page["limit"] == 2


def test_files_caps_limit(client: TestClient) -> None:
    resp = client.get("/api/v1/files?limit=100000")
    assert resp.json()["page"]["limit"] <= 100


def test_document_detail_masks_pii(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("src.intel.redact.redact_text", lambda t: t.replace(PII_EMAIL, "***"))
    resp = client.get("/api/v1/files/1?preview=200")
    assert resp.status_code == 200
    assert PII_EMAIL not in resp.text
    assert resp.json()["data"]["sensitivity"] in (None, "medium", "high", "low")


def test_show_paths_requires_explicit_flag(client: TestClient) -> None:
    resp = client.get("/api/v1/files/1?show_paths=1")
    assert "/private/dir/1.txt" in resp.text


def test_unknown_file_is_404_and_bad_id_is_400(client: TestClient) -> None:
    assert client.get("/api/v1/files/999999").status_code == 404
    assert client.get("/api/v1/files/abc").status_code == 400


def test_search_lexical_and_bounds(client: TestClient) -> None:
    resp = client.get("/api/v1/search?q=cancer")
    assert resp.status_code == 200
    assert any(r["id"] == 1 for r in resp.json()["data"])
    too_long = client.get("/api/v1/search?q=" + "a" * 600)
    assert too_long.status_code == 400


def test_search_semantic_degrades_gracefully(client: TestClient, monkeypatch) -> None:
    class _Unavailable:
        def __init__(self, _db): ...
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr("src.intelligence.semantic_search.SemanticSearchEngine", _Unavailable)
    resp = client.get("/api/v1/search?q=x&mode=semantic")
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_timeline_ingestion_doctor_and_maintenance(client: TestClient) -> None:
    assert client.get("/api/v1/timeline?limit=5").status_code == 200
    assert client.get("/api/v1/ingestion/issues").status_code == 200
    doctor = client.get("/api/v1/doctor")
    assert doctor.status_code == 200 and doctor.json()["data"]["status"]
    assert client.get("/api/v1/maintenance/status").status_code == 200
    assert client.get("/api/v1/duplicates").status_code == 200


def test_dossier_lifecycle_over_api(client: TestClient) -> None:
    created = client.post("/api/v1/dossiers", json={"name": "API dossier", "mode": "DYNAMIC",
                                                    "query": {"query": "cancer"}})
    assert created.status_code == 200
    did = created.json()["data"]["dossier_id"]
    assert client.get("/api/v1/dossiers").json()["data"]
    detail = client.get(f"/api/v1/dossiers/{did}")
    assert detail.status_code == 200
    added = client.post(f"/api/v1/dossiers/{did}/documents",
                        json={"document_ids": [2], "note": "manual"})
    assert added.json()["data"]["added"] == 1
    assert client.post(f"/api/v1/dossiers/{did}/freeze").json()["data"]["frozen_count"] >= 1


def test_report_build_dry_run_over_api(client: TestClient) -> None:
    resp = client.post("/api/v1/reports", json={"kind": "SEARCH", "title": "API report",
                                                "query": {"query": "cancer"},
                                                "generate": False})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["generated"] is False and data["logical_fingerprint"]
    assert client.get("/api/v1/reports").status_code == 200


def test_large_body_is_rejected(client: TestClient) -> None:
    big = {"name": "x" * (2 * 1024 * 1024)}
    resp = client.post("/api/v1/dossiers", json=big)
    assert resp.status_code == 413


def test_bind_warning_is_strong_for_non_loopback() -> None:
    assert bind_warning("127.0.0.1") is None
    warning = bind_warning("0.0.0.0")
    assert warning and "WARNING" in warning and "auth" in warning.lower()
