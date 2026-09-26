"""Read-only MCP prototype tests (M009F)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import src.mcp_server as mcp_server  # noqa: E402
from src.core.database import DatabaseManager  # noqa: E402
from src.core.scan_service import ScanRequest, ScanService  # noqa: E402
from src.core.volume import VolumeInfo  # noqa: E402


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "mcp.db"
    monkeypatch.setenv("PIS_DB_PATH", str(db_path))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "rapport.txt").write_text("rapport annuel sur le marché", encoding="utf-8")
    db = DatabaseManager()
    ScanService(db).run(
        ScanRequest(
            root=root,
            volume=VolumeInfo(stable_key="MCP", device="MCP", mountpoint=str(tmp_path), is_available=True),
        )
    )
    row = db.search_files(query="rapport")[0]
    db.update_content(row["id"], "rapport annuel detaille avec contenu extractible")
    return db_path


def test_search_files_tool(seeded: Path) -> None:
    rows = mcp_server.search_files(query="rapport", limit=5)
    assert len(rows) == 1
    assert rows[0]["filename"] == "rapport.txt"
    assert rows[0]["state"] == "ACTIVE"


def test_get_document_tool(seeded: Path) -> None:
    doc_id = mcp_server.search_files(query="rapport")[0]["id"]
    doc = mcp_server.get_document(file_id=doc_id)
    assert doc["filename"] == "rapport.txt"
    assert doc["content_extracted"] is True
    assert "content_preview" in doc
    assert isinstance(doc["content_preview"], str)


def test_get_document_missing(seeded: Path) -> None:
    assert "error" in mcp_server.get_document(path="/nope/missing.txt")


def test_semantic_search_falls_back_to_fts(seeded: Path, monkeypatch) -> None:
    from src.intelligence.semantic_search import SemanticSearchEngine

    monkeypatch.setattr(SemanticSearchEngine, "is_available", lambda self: False)
    rows = mcp_server.semantic_search("rapport", limit=5)
    assert len(rows) == 1


def test_build_server_registers_readonly_tools() -> None:
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"search_files", "get_document", "semantic_search"} <= names
