"""Privacy-aware search helpers and filter options (M015)."""
from __future__ import annotations

from typing import Any, cast


def filter_options(store: Any) -> dict[str, list[str]]:
    with store.db.get_connection() as conn:
        langs = [r[0] for r in conn.execute(
            "SELECT lang, COUNT(*) FROM doc_language GROUP BY lang ORDER BY 2 DESC").fetchall()]
        cats = [r[0] for r in conn.execute(
            "SELECT category, COUNT(*) FROM doc_categories GROUP BY category ORDER BY 2 DESC").fetchall()]
        entities = [r[0] for r in conn.execute(
            "SELECT entity_type, COUNT(*) FROM doc_entities GROUP BY entity_type ORDER BY 2 DESC").fetchall()]
    return {"languages": langs, "categories": cats, "entity_types": entities}


def search_with_intelligence(db: Any, query: str | None = None, **filters: Any) -> list[dict[str, Any]]:
    """Thin wrapper over the canonical search with M015 filters.

    Supported filters: ``language``, ``category``, ``has_pii``,
    ``exclude_high_sensitivity``, ``entity_type``, ``entity_value``.
    """
    return cast("list[dict[str, Any]]", db.search_files(query=query, **filters))
