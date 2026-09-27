"""Interpretable, evidence-backed topics derived from cluster content (M020).

A topic is a **human-readable description derived from cluster/content evidence**
— top c-TF-IDF terms, safe entities, a category signal and representative
documents — never an opaque AI label. Labels are deterministic first; an optional
local LLM refinement is intentionally *not* wired by default and would have to
retain the deterministic terms, provenance and fallback (see the docs).

Cluster ids are never silently equated with topics: the topic is a view built on
top of a clustering run, and ``unclustered``/noise is preserved.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from .text import ctfidf_terms, is_safe_term, tokenize

TOPIC_VERSION = "m020.1"
#: Entity types allowed into a human-readable label (PII-typed excluded).
LABEL_ENTITY_TYPES = {"ORGANIZATION", "LOCATION", "MONEY", "DATE", "URL"}
#: Types whose display value is masked even in evidence.
MASKED_ENTITY_TYPES = {"PERSON", "EMAIL", "PHONE", "IP", "IBAN", "CARD"}


@dataclass
class Topic:
    run_id: str
    cluster_id: int
    label: str
    terms: list[tuple[str, float]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    size: int = 0
    cohesion: float | None = None
    representatives: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "cluster_id": int(self.cluster_id),
            "label": self.label,
            "terms": [{"term": t, "weight": round(float(w), 6)} for t, w in self.terms],
            "entities": list(self.entities),
            "categories": list(self.categories),
            "size": int(self.size),
            "cohesion": (round(float(self.cohesion), 6) if self.cohesion is not None else None),
            "representatives": list(self.representatives),
            "evidence": dict(self.evidence),
        }


def label_from_evidence(terms: list[tuple[str, float]], entities: list[dict[str, Any]],
                        categories: list[dict[str, Any]], size: int) -> str:
    """Deterministic label: safe top terms, then a safe entity, then a category."""
    safe_terms = [t for t, _ in terms if is_safe_term(t)]
    parts = safe_terms[:4]
    for entity in entities:
        if entity.get("type") in LABEL_ENTITY_TYPES and entity.get("display"):
            display = str(entity["display"])[:32]
            if display and display not in parts:
                parts.append(display)
            break
    if not parts and categories:
        parts.append(str(categories[0].get("category", ""))[:32])
    label = " · ".join(p for p in parts if p) or f"cluster-{size} docs"
    return _mask_label(label)


def _mask_label(label: str) -> str:
    try:
        from ..intel.redact import redact_text
        return redact_text(label)
    except Exception:  # noqa: BLE001 - masking must never break label building
        return label


def _representatives(
    db: Any,
    member_ids: npt.NDArray[np.int64],
    vectors: npt.NDArray[np.float64],
    centroid: npt.NDArray[np.float64],
    *,
    limit: int,
    max_distance: float | None = None,
) -> list[dict[str, Any]]:
    """Nearest-to-centroid, diversity-aware representatives with a stated reason."""
    if len(member_ids) == 0:
        return []
    norm = np.linalg.norm(vectors, axis=1, keepdims=True)
    norm[norm == 0.0] = 1.0
    unit = vectors / norm
    cnorm = float(np.linalg.norm(centroid)) or 1.0
    sims = unit @ (centroid / cnorm)
    order = np.argsort(-sims)
    try:
        from ..dedup import DedupStore
        dedup = DedupStore(db)
    except Exception:  # noqa: BLE001 - dedup tables optional
        dedup = None
    seen_hashes: set[str] = set()
    seen_families: set[str] = set()
    picked: list[dict[str, Any]] = []
    for idx in order:
        if len(picked) >= limit:
            break
        fid = int(member_ids[int(idx)])
        similarity = float(sims[int(idx)])
        if max_distance is not None and (1.0 - similarity) > max_distance:
            continue
        reasons = ["nearest to cluster centroid"]
        if dedup is not None:
            digest = (dedup.get_hash(fid) or {}).get("digest")
            if digest:
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                reasons.append("content-diverse (exact duplicates skipped)")
            fam = dedup.get_version_family_for_file(fid)
            if fam:
                key = str(fam.get("family_key") or fam.get("id"))
                if key in seen_families:
                    continue
                seen_families.add(key)
                reasons.append("version-diverse (non-primary versions skipped)")
        picked.append({"id": fid, "similarity": round(similarity, 6),
                       "reason": "; ".join(reasons)})
    return picked


def _aggregate_intel(db: Any, ids: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not ids:
        return [], []
    entity_counts: Counter[tuple[str, str]] = Counter()
    entity_display: dict[tuple[str, str], str] = {}
    category_counts: Counter[str] = Counter()
    try:
        from ..intel import IntelStore
        store = IntelStore(db)
    except Exception:  # noqa: BLE001
        return [], []
    for fid in ids:
        for ent in store.get_entities(int(fid)):
            key = (str(ent.get("entity_type")), str(ent.get("normalized_value")))
            entity_counts[key] += int(ent.get("count", 1) or 1)
            display = ent.get("display_value")
            if display:
                entity_display[key] = str(display)
        for cat in store.get_categories(int(fid)):
            if cat.get("source") != "structural":
                category_counts[str(cat.get("category"))] += 1
    entities: list[dict[str, Any]] = []
    for (etype, normalized), count in entity_counts.most_common(12):
        display = entity_display.get((etype, normalized), normalized)
        if etype in MASKED_ENTITY_TYPES:
            display = _mask_label(display)
        entities.append({"type": etype, "value": normalized[:64], "display": display,
                         "documents": int(count)})
    categories = [{"category": c, "documents": n} for c, n in category_counts.most_common(8)]
    return entities, categories


def build_topics(
    db: Any,
    *,
    run_id: str,
    ids: list[int],
    labels: npt.NDArray[np.int64],
    centroids: npt.NDArray[np.float64],
    vectors: npt.NDArray[np.float64],
    cohesion_by_cluster: dict[int, float] | None = None,
    max_docs_per_cluster: int = 150,
    top_k_terms: int = 12,
    max_representatives: int = 5,
) -> list[Topic]:
    """Build one :class:`Topic` per non-noise cluster from bounded content samples."""
    labels = np.asarray(labels, dtype=np.int64)
    ids_arr = np.asarray(ids, dtype=np.int64)
    if len(ids_arr) != len(labels):
        raise ValueError("ids/labels length mismatch")
    topics: list[Topic] = []
    cluster_term_counts: dict[int, Counter[str]] = {}
    records: dict[int, dict[str, Any]] = {}

    for cid in sorted({int(c) for c in labels.tolist() if int(c) >= 0}):
        member_idx = np.where(labels == cid)[0]
        member_ids = ids_arr[member_idx]
        member_vecs = vectors[member_idx]
        centroid = centroids[cid] if cid < len(centroids) else member_vecs.mean(axis=0)
        reps = _representatives(db, member_ids, member_vecs, centroid,
                                limit=max_representatives)
        for rep in reps:
            rep["label"] = _mask_label(_filename_for(db, int(rep["id"])))
        # Term/document evidence uses the nearest/most representative documents,
        # then tops up (deterministically by id) for breadth, bounded per cluster.
        sample_ids = [int(r["id"]) for r in reps][:max_docs_per_cluster]
        already = set(sample_ids)
        if len(sample_ids) < min(max_docs_per_cluster, len(member_ids)):
            for fid in sorted(int(x) for x in member_ids.tolist()):
                if len(sample_ids) >= max_docs_per_cluster:
                    break
                if fid not in already:
                    sample_ids.append(fid)
                    already.add(fid)
        counts: Counter[str] = Counter()
        for fid in sample_ids:
            counts.update(tokenize(_content_for(db, fid), max_tokens=2000))
        cluster_term_counts[cid] = counts
        ents, cats = _aggregate_intel(db, sample_ids)
        records[cid] = {"reps": reps, "entities": ents, "categories": cats,
                        "sample_count": len(sample_ids),
                        "size": int(np.sum(labels == cid))}

    global_counts: Counter[str] = Counter()
    for counts in cluster_term_counts.values():
        global_counts.update(counts)
    weighted = ctfidf_terms(cluster_term_counts, global_counts, top_k=top_k_terms)

    for cid in sorted(cluster_term_counts):
        terms = weighted.get(cid, [])
        rec = records[cid]
        label = label_from_evidence(terms, rec["entities"], rec["categories"], rec["size"])
        topics.append(Topic(
            run_id=run_id, cluster_id=cid, label=label, terms=terms,
            entities=rec["entities"], categories=rec["categories"],
            size=rec["size"],
            cohesion=(cohesion_by_cluster or {}).get(cid),
            representatives=rec["reps"],
            evidence={
                "method": "c-tf-idf + entities + categories",
                "version": TOPIC_VERSION,
                "terms": [t for t, _ in terms],
                "documents_sampled": rec["sample_count"],
                "label_source": "deterministic",
                "llm_refined": False,
                "note": "a topic is a description of cluster evidence, not ground truth",
            },
        ))
    return topics


def _content_for(db: Any, file_id: int) -> str:
    with db.get_connection() as conn:
        row = conn.execute("SELECT content_text FROM files WHERE id=?", (int(file_id),)).fetchone()
    return str(row[0]) if row and row[0] else ""


def _filename_for(db: Any, file_id: int) -> str:
    with db.get_connection() as conn:
        row = conn.execute("SELECT filename FROM files WHERE id=?", (int(file_id),)).fetchone()
    return str(row[0]) if row and row[0] else ""
