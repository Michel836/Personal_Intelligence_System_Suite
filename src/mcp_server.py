"""Read-only MCP server exposing the local 36TB Intelligence index.

Prototype (M009F). Exposes three read-only tools over stdio:

* ``search_files``    -- canonical FTS metadata search
* ``get_document``    -- metadata + extracted-content preview for one document
* ``semantic_search`` -- embedding search when available, else FTS fallback

The server never writes: no scans, no content updates, no deletes. It honours
``PIS_DB_PATH`` (see ``DatabaseManager.default_db_path``).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from .core.database import DatabaseManager, default_db_path

_PREVIEW_CHARS = 2000
_MAX_PREVIEW_CHARS = 20000
_MAX_SEARCH_RESULTS = 100


def _db() -> DatabaseManager:
    return DatabaseManager()


def _allowed_roots() -> list[str]:
    raw = os.environ.get("PIS_MCP_ALLOWED_ROOTS", "")
    roots = []
    for part in raw.replace(os.pathsep, ",").split(","):
        part = part.strip()
        if part:
            roots.append(os.path.realpath(part))
    return roots


def _allowed_roots_error(normalized_path: str) -> Optional[str]:
    roots = _allowed_roots()
    if not roots:
        return None  # indexed-only restriction still applies via the DB lookup
    for root in roots:
        if normalized_path == root or normalized_path.startswith(root + os.sep):
            return None
    return "path outside allowed roots"


def _public_row(row: dict[str, Any], *, preview: bool = False, max_chars: int = _PREVIEW_CHARS) -> dict[str, Any]:
    out = {
        "id": row.get("id"),
        "filename": row.get("filename"),
        "path": row.get("path"),
        "extension": row.get("extension"),
        "size_bytes": row.get("size_bytes"),
        "file_type": row.get("file_type"),
        "priority": row.get("priority"),
        "modified_at": row.get("modified_at"),
        "state": row.get("state"),
        "content_extracted": bool(row.get("content_extracted")),
    }
    if preview:
        content = row.get("content_text") or ""
        out["content_preview"] = content[:max_chars]
        out["content_truncated"] = len(content) > max_chars
    return out


def search_files(
    query: Optional[str] = None,
    limit: int = 20,
    extension: Optional[str] = None,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    """Read-only metadata search over the index (canonical FTS path)."""
    limit = max(1, min(int(limit), 100))
    rows = _db().search_files(
        query=query, limit=limit, extension=extension, include_missing=include_missing
    )
    return [_public_row(r) for r in rows]


def get_document(
    file_id: Optional[int] = None,
    path: Optional[str] = None,
    max_chars: int = _PREVIEW_CHARS,
) -> dict[str, Any]:
    """Return metadata and an extracted-content preview for a single document.

    Only indexed rows are reachable; when ``PIS_MCP_ALLOWED_ROOTS`` is set, the
    normalized path must also fall under one of those roots.
    """
    if file_id is None and path is None:
        return {"error": "provide file_id or path"}
    preview = max(0, min(int(max_chars), _MAX_PREVIEW_CHARS))
    db = _db()
    with db.get_connection() as conn:
        if file_id is not None:
            row = conn.execute("SELECT * FROM files WHERE id = ?", (int(file_id),)).fetchone()
        else:
            raw = str(path)
            if "\x00" in raw:
                return {"error": "invalid path"}
            normalized = os.path.realpath(raw)
            root_error = _allowed_roots_error(normalized)
            if root_error:
                return {"error": root_error, "path": raw}
            row = conn.execute(
                "SELECT * FROM files WHERE path = ? OR path = ?", (raw, normalized)
            ).fetchone()
    if row is None:
        return {"error": "not found", "file_id": file_id, "path": path}
    return _public_row(dict(row), preview=True, max_chars=preview)


def semantic_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Semantic search when embeddings are available, else FTS fallback."""
    limit = max(1, min(int(limit), 50))
    try:
        from .intelligence.semantic_search import SemanticSearchEngine

        engine = SemanticSearchEngine()
        if engine.is_available():
            model_key = getattr(engine.embedding_gen, "model_key", None)
            dim = getattr(engine.embedding_gen, "embedding_dim", None)
            rows = [_public_row(r) for r in engine.semantic_search(query, limit=limit)]
            for row in rows:
                row["embedding_model"] = model_key
                row["embedding_dim"] = dim
            return rows
    except Exception as exc:  # noqa: BLE001 - degrade to FTS
        logger.warning(f"semantic_search unavailable, falling back to FTS: {exc}")
    rows = search_files(query=query, limit=limit)
    for row in rows:
        row["embedding_model"] = None
        row["embedding_dim"] = None
    return rows


def build_server():
    """Build the MCPServer with the read-only tools registered."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        "36TB Intelligence (read-only)",
        instructions=(
            "Read-only access to the local personal index. "
            f"Database: {default_db_path()}"
        ),
    )
    server.add_tool(search_files, description="Search indexed files by lexical query/filters.")
    server.add_tool(get_document, description="Get metadata + content preview for one document.")
    server.add_tool(semantic_search, description="Semantic search (falls back to lexical).")
    return server


def main() -> None:
    transport = os.environ.get("PIS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport != "stdio" and os.environ.get("PIS_MCP_ALLOW_REMOTE", "0") != "1":
        raise SystemExit(
            "refusing non-stdio MCP transport without PIS_MCP_ALLOW_REMOTE=1"
        )
    build_server().run(transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
