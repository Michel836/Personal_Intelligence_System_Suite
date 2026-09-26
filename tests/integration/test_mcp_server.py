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
    assert names == {"search_files", "get_document", "semantic_search"}
    assert not any(token in n.lower() for n in names for token in ("write", "delete", "scan", "update"))


def test_get_document_rejects_path_outside_allowed_roots(seeded: Path, tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("PIS_MCP_ALLOWED_ROOTS", str(allowed))
    result = mcp_server.get_document(path="/etc/passwd")
    assert result["error"] == "path outside allowed roots"


def test_get_document_rejects_traversal(seeded: Path, tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("PIS_MCP_ALLOWED_ROOTS", str(allowed))
    result = mcp_server.get_document(path=str(allowed / ".." / "escape.txt"))
    assert result["error"] == "path outside allowed roots"


def test_get_document_rejects_null_byte(seeded: Path) -> None:
    result = mcp_server.get_document(path="rapport\x00.txt")
    assert result["error"] == "invalid path"


def test_preview_is_capped(seeded: Path) -> None:
    doc_id = mcp_server.search_files(query="rapport")[0]["id"]
    doc = mcp_server.get_document(file_id=doc_id, max_chars=10_000_000)
    assert len(doc["content_preview"]) <= mcp_server._MAX_PREVIEW_CHARS


def test_remote_transport_refused_without_flag(monkeypatch) -> None:
    monkeypatch.setenv("PIS_MCP_TRANSPORT", "sse")
    monkeypatch.delenv("PIS_MCP_ALLOW_REMOTE", raising=False)
    with pytest.raises(SystemExit):
        mcp_server.main()
