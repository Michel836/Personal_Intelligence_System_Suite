"""Explainable document prioritization (M016).

A transparent weighted sum of bounded, named signals. Every contribution is
returned so the score can never hide *why* a document ranks where it does. User
signals (favorite, tag) dominate weak inferred signals; PII/sensitivity is a
*filter*, never an importance signal.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

#: (weight, human label)
WEIGHTS = {
    "favorite": (3.0, "marked as favorite"),
    "user_tag": (2.0, "has user tags"),
    "query_match": (1.5, "matches the query in name/path"),
    "entity_match": (1.0, "query matches a mention"),
    "centrality": (1.0, "relationship-graph degree"),
    "category_relevance": (0.5, "topic category relevance"),
    "recency": (0.5, "recent modification"),
}
PENALTIES = {"duplicate_suppression": (0.5, "redundant copy (exact duplicate/non-primary version)")}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def compute_priority(db: Any, file_id: int, *, query: str | None = None,
                     intel_store: Any = None, dedup_store: Any = None, tag_manager: Any = None,
                     relation_service: Any = None, degree: int | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    fid = int(file_id)
    components: list[dict[str, Any]] = []
    raw: dict[str, float] = {}

    # -- user signals (dominant) ------------------------------------------
    favorite = False
    tag_count = 0
    tm = tag_manager
    if tm is None:
        try:
            from ..tags.tag_manager import TagManager
            tm = TagManager(getattr(db, "db_path", None))  # type: ignore[no-untyped-call]
        except Exception:
            tm = None
    if tm is not None:
        try:
            favorite = bool(tm.is_favorite(fid))
            tag_count = len(tm.get_file_tags(fid))
        except Exception:
            favorite, tag_count = False, 0
    if favorite:
        raw["favorite"] = 1.0
    if tag_count:
        raw["user_tag"] = min(1.0, tag_count / 3.0)

    # -- query relevance ---------------------------------------------------
    if query and query.strip():
        with db.get_connection() as conn:
            row = conn.execute("SELECT filename, path FROM files WHERE id=?", (fid,)).fetchone()
        hay = ((row["filename"] if row else "") or "") + " " + ((row["path"] if row else "") or "")
        hay = hay.lower()
        tokens = [t for t in query.lower().split() if t]
        if tokens and all(t in hay for t in tokens):
            raw["query_match"] = 1.0
        entities = []
        if intel_store is not None:
            entities = intel_store.get_entities(fid)
        elif relation_service is not None:
            try:
                entities = relation_service.intel().get_entities(fid)
            except Exception:
                entities = []
        if tokens:
            for e in entities:
                disp = ((e.get("display_value") or "") + " " + (e.get("normalized_value") or "")).lower()
                if any(t in disp for t in tokens):
                    raw["entity_match"] = 1.0
                    break

    # -- metadata relevance -----------------------------------------------
    store = intel_store
    if store is None and relation_service is not None:
        try:
            store = relation_service.intel()
        except Exception:
            store = None
    if store is not None:
        cats = store.get_categories(fid)
        topic = [c for c in cats if c.get("source") != "structural"]
        if topic:
            raw["category_relevance"] = min(1.0, float(topic[0].get("score") or 0.0))

    # -- centrality (bounded degree passed in) ----------------------------
    if degree is not None and degree > 0:
        raw["centrality"] = min(1.0, math.log1p(degree) / math.log1p(20))

    # -- recency -----------------------------------------------------------
    with db.get_connection() as conn:
        row = conn.execute("SELECT modified_at FROM files WHERE id=?", (fid,)).fetchone()
    dt = _parse_dt(row["modified_at"] if row else None)
    if dt is not None:
        ref = now or datetime.now()  # noqa: DTZ005
        age_days = max(0.0, (ref - dt).total_seconds() / 86400.0)
        raw["recency"] = math.exp(-age_days / 365.0)

    # -- duplicate suppression (penalty) ----------------------------------
    if dedup_store is not None:
        fam = dedup_store.get_version_family_for_file(fid)
        if fam:
            member = next((m for m in fam.get("members", []) if int(m["id"]) == fid), None)
            if member is not None and not member.get("is_primary"):
                raw["duplicate_suppression"] = 1.0

    total_weight = sum(WEIGHTS[k][0] for k in raw if k in WEIGHTS) or 1.0
    score = sum(raw.get(k, 0.0) * WEIGHTS[k][0] for k in WEIGHTS) / total_weight
    score -= sum(raw.get(k, 0.0) * PENALTIES[k][0] for k in PENALTIES)
    score = max(0.0, min(1.0, score))

    for key, (weight, label) in WEIGHTS.items():
        components.append({"signal": key, "label": label, "value": round(raw.get(key, 0.0), 4),
                           "weight": weight,
                           "contribution": round(raw.get(key, 0.0) * weight / total_weight, 4)})
    for key, (weight, label) in PENALTIES.items():
        if raw.get(key):
            components.append({"signal": key, "label": label, "value": round(raw[key], 4),
                               "weight": -weight, "contribution": round(-raw[key] * weight, 4)})

    user_signals = bool(raw.get("favorite") or raw.get("user_tag"))
    return {"file_id": fid, "score": round(score, 4),
            "components": sorted(components, key=lambda c: -abs(c["contribution"])),
            "user_signals_present": user_signals,
            "note": "PII/sensitivity is a filter, not an importance signal."}


def rank_documents(db: Any, file_ids: list[int], **kwargs: Any) -> list[dict[str, Any]]:
    results = [compute_priority(db, fid, **kwargs) for fid in file_ids]
    return sorted(results, key=lambda r: (-r["score"], r["file_id"]))
