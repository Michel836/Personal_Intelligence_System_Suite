"""Canonical document/entity relationship service (M016).

Relations are **queried from the existing canonical tables** (content hashes,
near-duplicate edges, version families, archive links, entities, categories,
tags/favorites) rather than duplicated into a parallel model. Every relation
carries a type, score, evidence, provenance and explicit direction.

No relation is ever phrased as a human/social fact: a shared entity means
"both documents mention this entity", nothing more.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class RelationType(str, Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    VERSION_OF = "VERSION_OF"
    SEMANTIC_RELATED = "SEMANTIC_RELATED"
    ARCHIVE_CONTAINS = "ARCHIVE_CONTAINS"
    SAME_ENTITY = "SAME_ENTITY"
    SAME_CATEGORY = "SAME_CATEGORY"
    SAME_LANGUAGE = "SAME_LANGUAGE"
    PATH_CONTEXT = "PATH_CONTEXT"
    USER_TAG = "USER_TAG"
    FAVORITE = "FAVORITE"
    TEMPORAL_PROXIMITY = "TEMPORAL_PROXIMITY"


#: Directed types (source -> target). Everything else is undirected.
DIRECTED = {RelationType.ARCHIVE_CONTAINS, RelationType.VERSION_OF}

DEFAULT_NEIGHBORHOOD_TYPES = {
    RelationType.EXACT_DUPLICATE, RelationType.NEAR_DUPLICATE, RelationType.VERSION_OF,
    RelationType.SEMANTIC_RELATED, RelationType.ARCHIVE_CONTAINS, RelationType.SAME_ENTITY,
    RelationType.USER_TAG, RelationType.FAVORITE,
}
#: Potentially high-degree types — opt-in and always bounded.
OPTIONAL_TYPES = {
    RelationType.SAME_CATEGORY, RelationType.SAME_LANGUAGE,
    RelationType.PATH_CONTEXT, RelationType.TEMPORAL_PROXIMITY,
}
ALL_TYPES = {t.value for t in RelationType}


@dataclass(frozen=True)
class Relation:
    source: int
    target: int
    type: str  # noqa: A003 - relation type is the contract name
    score: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    directed: bool = False
    provenance: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "type": self.type,
                "score": round(float(self.score), 5), "evidence": self.evidence,
                "directed": self.directed, "provenance": self.provenance}

    def key(self) -> tuple[Any, ...]:
        if self.directed:
            return (self.type, self.source, self.target)
        a, b = sorted((self.source, self.target))
        return (self.type, a, b)


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


class RelationService:
    def __init__(self, db: Any, *, dedup_store: Any = None, intel_store: Any = None, tag_manager: Any = None,
                 related: Any = None) -> None:
        self.db = db
        self._dedup = dedup_store
        self._intel = intel_store
        self._tags = tag_manager
        self._related = related

    # -- lazy helpers ------------------------------------------------------
    def dedup(self) -> Any:
        if self._dedup is None:
            from ..dedup import DedupStore
            self._dedup = DedupStore(self.db)
        return self._dedup

    def intel(self) -> Any:
        if self._intel is None:
            from ..intel import IntelStore
            self._intel = IntelStore(self.db)
        return self._intel

    def tags(self) -> Any:
        if self._tags is None:
            try:
                from ..tags.tag_manager import TagManager
                self._tags = TagManager(getattr(self.db, "db_path", None))  # type: ignore[no-untyped-call]
            except Exception as exc:  # noqa: BLE001 - user signals are optional
                logger.debug(f"tag manager unavailable: {exc}")
                self._tags = False
        return self._tags or None

    # -- document metadata -------------------------------------------------
    def document(self, file_id: int) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT id, path, filename, parent_dir, extension, document_kind, "
                "archive_parent_id, modified_at, COALESCE(state,'ACTIVE') AS state "
                "FROM files WHERE id=?", (int(file_id),)).fetchone()
        return dict(row) if row else None

    # -- per-document relations -------------------------------------------
    def relations_for(self, file_id: int, *, types: Iterable[str] | None = None,
                      max_per_type: int = 20, semantic: bool = False) -> list[Relation]:
        fid = int(file_id)
        wanted = {t if isinstance(t, str) else getattr(t, "value", str(t)) for t in (types or DEFAULT_NEIGHBORHOOD_TYPES)}
        out: list[Relation] = []
        if RelationType.EXACT_DUPLICATE.value in wanted:
            out.extend(self._exact(fid, max_per_type))
        if RelationType.NEAR_DUPLICATE.value in wanted:
            out.extend(self._near(fid, max_per_type))
        if RelationType.VERSION_OF.value in wanted:
            out.extend(self._version(fid, max_per_type))
        if RelationType.ARCHIVE_CONTAINS.value in wanted:
            out.extend(self._archive(fid, max_per_type))
        if RelationType.SAME_ENTITY.value in wanted:
            out.extend(self._same_entity(fid, max_per_type))
        if RelationType.USER_TAG.value in wanted:
            out.extend(self._user_tag(fid, max_per_type))
        if RelationType.FAVORITE.value in wanted:
            out.extend(self._favorite(fid, max_per_type))
        if RelationType.PATH_CONTEXT.value in wanted:
            out.extend(self._path_context(fid, max_per_type))
        if RelationType.SAME_CATEGORY.value in wanted:
            out.extend(self._same_category(fid, max_per_type))
        if RelationType.TEMPORAL_PROXIMITY.value in wanted:
            out.extend(self._temporal(fid, max_per_type))
        if RelationType.SAME_LANGUAGE.value in wanted:
            out.extend(self._same_language(fid, max_per_type))
        if semantic and RelationType.SEMANTIC_RELATED.value in wanted:
            out.extend(self._semantic(fid, max_per_type))
        return out

    def _exact(self, fid: int, limit: int) -> list[Relation]:
        h = self.dedup().get_hash(fid)
        if not h or not h.get("digest"):
            return []
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT h.file_id, h.state FROM content_hashes h JOIN files f ON f.id=h.file_id "
                "WHERE h.state='OK' AND h.digest=? AND h.file_id != ? "
                "AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?",
                (h["digest"], fid, int(limit))).fetchall()
        return [Relation(fid, int(r[0]), RelationType.EXACT_DUPLICATE.value, 1.0,
                         {"digest": h["digest"][:12] + "…"}, False, "content_hashes")
                for r in rows]

    def _near(self, fid: int, limit: int) -> list[Relation]:
        edges = self.dedup().near_duplicates_for(fid, limit=limit)
        return [Relation(fid, e["other_id"], RelationType.NEAR_DUPLICATE.value,
                         float(e.get("semantic_score") or 0.0),
                         {"reason": e.get("reason"), "lexical": e.get("lexical_score")},
                         False, "near_duplicate_edges") for e in edges]

    def _version(self, fid: int, limit: int) -> list[Relation]:
        fam = self.dedup().get_version_family_for_file(fid)
        if not fam:
            return []
        primary = None
        members = fam.get("members", [])
        for m in members:
            if m.get("is_primary"):
                primary = int(m["id"])
        if primary is None and members:
            primary = int(max(members, key=lambda m: m.get("rank") or 0)["id"])
        out = []
        for m in members:
            mid = int(m["id"])
            if mid == fid:
                continue
            out.append(Relation(fid, mid, RelationType.VERSION_OF.value,
                                float(fam.get("member_count") or 0) and 0.8,
                                {"family": fam.get("family_key"), "confidence": fam.get("confidence"),
                                 "rank": m.get("rank"), "primary": primary},
                                True, "version_members"))
        return out[:limit]

    def _archive(self, fid: int, limit: int) -> list[Relation]:
        doc = self.document(fid)
        out: list[Relation] = []
        if doc is None:
            return out
        if doc.get("document_kind") == "ARCHIVE_MEMBER" and doc.get("archive_parent_id"):
            out.append(Relation(int(doc["archive_parent_id"]), fid, RelationType.ARCHIVE_CONTAINS.value,
                                1.0, {"role": "member"}, True, "files.archive_parent_id"))
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM files WHERE archive_parent_id=? AND COALESCE(state,'ACTIVE')='ACTIVE' "
                "LIMIT ?", (fid, int(limit))).fetchall()
        for r in rows:
            out.append(Relation(fid, int(r[0]), RelationType.ARCHIVE_CONTAINS.value, 1.0,
                                {"role": "parent"}, True, "files.archive_parent_id"))
        return out

    def _same_entity(self, fid: int, limit: int) -> list[Relation]:
        store = self.intel()
        out: list[Relation] = []
        for e in store.get_entities(fid):
            if len(out) >= limit:
                break
            others = store.entity_documents(e["entity_type"], e["normalized_value"], limit=limit)
            for o in others:
                if int(o["id"]) == fid:
                    continue
                out.append(Relation(fid, int(o["id"]), RelationType.SAME_ENTITY.value,
                                    float(e.get("confidence") or 0.0),
                                    {"entity_type": e["entity_type"], "display": e.get("display_value"),
                                     "note": "both documents mention this entity"},
                                    False, "doc_entities"))
                if len(out) >= limit:
                    break
        return out[:limit]

    def _same_category(self, fid: int, limit: int) -> list[Relation]:
        store = self.intel()
        out: list[Relation] = []
        for c in store.get_categories(fid):
            if c.get("source") == "structural":
                continue
            with store.db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT dc.file_id, dc.score FROM doc_categories dc JOIN files f ON f.id=dc.file_id "
                    "WHERE dc.category=? AND dc.file_id != ? AND COALESCE(f.state,'ACTIVE')='ACTIVE' "
                    "ORDER BY dc.score DESC LIMIT ?", (c["category"], fid, int(limit))).fetchall()
            for r in rows:
                out.append(Relation(fid, int(r[0]), RelationType.SAME_CATEGORY.value,
                                    float(r[1] or 0.0), {"category": c["category"]}, False, "doc_categories"))
        return out[:limit]

    def _same_language(self, fid: int, limit: int) -> list[Relation]:
        store = self.intel()
        lang = store.get_language(fid)
        if not lang:
            return []
        with store.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT dl.file_id FROM doc_language dl JOIN files f ON f.id=dl.file_id "
                "WHERE dl.lang=? AND dl.file_id != ? AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?",
                (lang["lang"], fid, int(limit))).fetchall()
        return [Relation(fid, int(r[0]), RelationType.SAME_LANGUAGE.value,
                         float(lang.get("confidence") or 0.0), {"lang": lang["lang"]}, False,
                         "doc_language") for r in rows]

    def _path_context(self, fid: int, limit: int) -> list[Relation]:
        doc = self.document(fid)
        if not doc or not doc.get("parent_dir"):
            return []
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM files WHERE parent_dir=? AND id != ? AND COALESCE(state,'ACTIVE')='ACTIVE' "
                "ORDER BY modified_at DESC LIMIT ?", (doc["parent_dir"], fid, int(limit))).fetchall()
        return [Relation(fid, int(r[0]), RelationType.PATH_CONTEXT.value, 0.3,
                         {"parent_dir": doc["parent_dir"]}, False, "files.parent_dir") for r in rows]

    def _temporal(self, fid: int, limit: int, *, window_days: int = 1) -> list[Relation]:
        doc = self.document(fid)
        if not doc or not doc.get("modified_at"):
            return []
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, modified_at FROM files WHERE id != ? AND modified_at IS NOT NULL "
                "AND ABS(julianday(modified_at) - julianday(?)) <= ? "
                "AND COALESCE(state,'ACTIVE')='ACTIVE' LIMIT ?",
                (fid, doc["modified_at"], float(window_days), int(limit))).fetchall()
        return [Relation(fid, int(r[0]), RelationType.TEMPORAL_PROXIMITY.value,
                         max(0.0, 1.0 - abs(window_days) / max(window_days, 1)),
                         {"window_days": window_days, "date_source": "modified_at"}, False,
                         "files.modified_at") for r in rows]

    def _user_tag(self, fid: int, limit: int) -> list[Relation]:
        tm = self.tags()
        if tm is None:
            return []
        tags = tm.get_file_tags(fid)
        out = []
        for t in tags:
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT ft.file_id FROM file_tags ft JOIN files f ON f.id=ft.file_id "
                    "WHERE ft.tag_id=? AND ft.file_id != ? AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?",
                    (t["id"], fid, int(limit))).fetchall()
            for r in rows:
                out.append(Relation(fid, int(r[0]), RelationType.USER_TAG.value, 1.0,
                                    {"tag": t.get("name")}, False, "file_tags"))
        return out[:limit]

    def _favorite(self, fid: int, limit: int) -> list[Relation]:
        tm = self.tags()
        if tm is None:
            return []
        with self.db.get_connection() as conn:
            if conn.execute("SELECT 1 FROM favorites WHERE file_id=?", (fid,)).fetchone() is None:
                return []
            rows = conn.execute(
                "SELECT file_id FROM favorites WHERE file_id != ? LIMIT ?", (fid, int(limit))).fetchall()
        return [Relation(fid, int(r[0]), RelationType.FAVORITE.value, 1.0, {}, False, "favorites")
                for r in rows]

    def _semantic(self, fid: int, limit: int) -> list[Relation]:
        try:
            from ..dedup.related import RelatedDocuments
            if self._related is None:
                import os
                base = os.environ.get("PIS_EMBEDDING_STORE_DIR")
                if not base:
                    return []
                from ..intelligence.embedding_store import EmbeddingMatrixStore
                estore = EmbeddingMatrixStore("bge-m3", "BAAI/bge-m3", 1024, base_dir=Path(base))
                if not estore.load():
                    return []
                self._related = RelatedDocuments(self.db, dedup_store=self.dedup(), embed_store=estore)
            docs = self._related.related(fid, limit=limit)
            return [Relation(fid, int(d["id"]), RelationType.SEMANTIC_RELATED.value,
                             float(d.get("semantic_similarity") or 0.0), {"reason": d.get("reason")},
                             False, "embedding_store") for d in docs]
        except Exception as exc:  # noqa: BLE001 - semantic relations are optional
            logger.debug(f"semantic relations unavailable: {exc}")
            return []

    # -- bounded neighborhood ---------------------------------------------
    def neighborhood(self, file_id: int, *, types: Iterable[str] | None = None,
                     depth: int = 1, max_nodes: int = 50, max_edges: int = 120,
                     semantic: bool = False) -> dict[str, Any]:
        depth = max(1, min(int(depth), 2))
        nodes: set[int] = {int(file_id)}
        edges: dict[tuple[Any, ...], Relation] = {}
        frontier = [int(file_id)]
        for _ in range(depth):
            next_frontier: list[int] = []
            for nid in frontier:
                if len(nodes) >= max_nodes or len(edges) >= max_edges:
                    break
                for rel in self.relations_for(nid, types=types, semantic=semantic):
                    other = rel.target if rel.source == nid else rel.source
                    key = rel.key()
                    if key not in edges:
                        edges[key] = rel
                    if other not in nodes and len(nodes) < max_nodes:
                        nodes.add(other)
                        next_frontier.append(other)
                if len(edges) >= max_edges:
                    break
            frontier = next_frontier
            if not frontier:
                break
        return self._materialize(nodes, list(edges.values()))

    def _materialize(self, node_ids: Iterable[int], relations: list[Relation]) -> dict[str, Any]:
        ids = list(dict.fromkeys(int(i) for i in node_ids))
        docs: dict[int, dict[str, Any]] = {}
        if ids:
            ph = ",".join("?" * len(ids))
            with self.db.get_connection() as conn:
                for r in conn.execute(
                        f"SELECT id, filename, extension, document_kind, COALESCE(state,'ACTIVE') AS state "
                        f"FROM files WHERE id IN ({ph})", ids):
                    docs[int(r["id"])] = dict(r)
        nodes = [{"id": i, **docs.get(i, {"filename": None, "state": "MISSING"})} for i in ids]
        return {"nodes": nodes, "edges": [r.as_dict() for r in relations]}

    # -- entity graph ------------------------------------------------------
    def entity_graph(self, *, scope_prefix: str | None = None, min_docs: int = 2,  # noqa: ARG002
                     max_entities: int = 200, max_edges: int = 1000,
                     entity_types: Iterable[str] | None = None,
                     co_occurrence: bool = False) -> dict[str, Any]:
        self.intel()
        type_filter = list(entity_types) if entity_types else None
        sql = ("SELECT entity_type, normalized_value, MAX(display_value) AS display, "
               "COUNT(DISTINCT file_id) AS docs FROM doc_entities")
        params: list[Any] = []
        if type_filter:
            sql += " WHERE entity_type IN (" + ",".join("?" * len(type_filter)) + ")"
            params.extend(type_filter)
        sql += " GROUP BY entity_type, normalized_value HAVING COUNT(DISTINCT file_id) >= ? "
        sql += "ORDER BY docs DESC LIMIT ?"
        params.extend([int(min_docs), int(max_entities)])
        with self.db.get_connection() as conn:
            entities = [dict(r) for r in conn.execute(sql, params).fetchall()]

        nodes = [{"id": f"e:{e['entity_type']}:{e['normalized_value']}", "kind": "entity",
                  "entity_type": e["entity_type"], "label": e.get("display") or e["normalized_value"],
                  "docs": int(e["docs"])} for e in entities]
        edges: list[dict[str, Any]] = []
        entity_keys = {(e["entity_type"], e["normalized_value"]) for e in entities}
        for e in entities:
            if len(edges) >= max_edges:
                break
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT de.file_id FROM doc_entities de JOIN files f ON f.id=de.file_id "
                    "WHERE de.entity_type=? AND de.normalized_value=? "
                    "AND COALESCE(f.state,'ACTIVE')='ACTIVE' LIMIT ?",
                    (e["entity_type"], e["normalized_value"], max(5, max_edges // max(len(entities), 1)))).fetchall()
            for r in rows:
                edges.append({"source": f"e:{e['entity_type']}:{e['normalized_value']}",
                              "target": f"d:{int(r[0])}", "type": "MENTIONS", "score": 1.0,
                              "evidence": {"entity_type": e["entity_type"]}})
                if len(edges) >= max_edges:
                    break
        if co_occurrence:
            # Entity-entity CO_OCCURS_WITH over documents sharing >=2 entities,
            # explicitly excluding PERSON/ORGANIZATION to avoid implying social facts.
            excluded = {"PERSON", "ORGANIZATION"}
            pairs: dict[tuple[str, str], int] = {}
            with self.db.get_connection() as conn:
                for (fid,) in conn.execute(
                        "SELECT DISTINCT file_id FROM doc_entities LIMIT 5000").fetchall():
                    ents = [r[0] for r in conn.execute(
                        "SELECT entity_type || ':' || normalized_value FROM doc_entities WHERE file_id=?",
                        (int(fid),)).fetchall()]
                    ents = [x for x in ents if x.split(":", 1)[0] not in excluded]
                    for i in range(len(ents)):
                        for j in range(i + 1, len(ents)):
                            a, b = sorted((ents[i], ents[j]))
                            pairs[(a, b)] = pairs.get((a, b), 0) + 1
            for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1])[:max_edges]:
                at, an = a.split(":", 1)
                bt, bn = b.split(":", 1)
                if (at, an) in entity_keys and (bt, bn) in entity_keys:
                    edges.append({"source": f"e:{a}", "target": f"e:{b}", "type": "CO_OCCURS_WITH",
                                  "score": float(n), "evidence": {"documents": n,
                                  "note": "these entities occur in the same documents, nothing more"}})
        return {"nodes": nodes, "edges": edges[:max_edges],
                "stats": {"entities": len(nodes), "edges": len(edges[:max_edges]),
                          "co_occurrence": co_occurrence}}

    def stats(self) -> dict[str, Any]:
        counts = {}
        with self.db.get_connection() as conn:
            for label, sql in {
                "content_hashes": "SELECT COUNT(*) FROM content_hashes WHERE state='OK'",
                "near_edges": "SELECT COUNT(*) FROM near_duplicate_edges",
                "version_members": "SELECT COUNT(*) FROM version_members",
                "entities": "SELECT COUNT(*) FROM doc_entities",
                "archive_links": "SELECT COUNT(*) FROM files WHERE archive_parent_id IS NOT NULL",
                "favorites": "SELECT COUNT(*) FROM favorites",
                "file_tags": "SELECT COUNT(*) FROM file_tags",
            }.items():
                try:
                    counts[label] = int(conn.execute(sql).fetchone()[0])
                except Exception:
                    counts[label] = 0
        return counts
