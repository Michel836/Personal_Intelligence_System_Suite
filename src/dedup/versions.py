"""Version-family tracking with explicit, evidence-based confidence.

Chronology is only inferred from explicit version markers (numeric/date suffix)
or, failing that, modification times labelled as *probable*. Similarity alone
never invents an order.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from loguru import logger

from .store import DedupStore, _like_prefix

_COMPOUND_EXT = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")

# Explicit version markers we are willing to order on.
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{2})[-_.]?(\d{2})[-_.]?(20\d{2})(?!\d)"),
)
_NUM_RE = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")
_VERSION_WORDS = re.compile(
    r"(?:^|[\s_\-\.\(\[\{])(v|ver|version|rev|revision|final|finale|copy|copie|old|new|"
    r"backup|sauvegarde|draft|brouillon|updated|modifie|modifiée|dernier|last|"
    r"latest|ancien|origine|original)(?:[\s_\-\.\)\]\}]|$)", re.I)


def strip_compound_ext(name: str) -> str:
    lower = name.lower()
    for ext in _COMPOUND_EXT:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name.rsplit(".", 1)[0] if "." in name else name


def normalize_stem(name: str) -> str:
    """Return a version-insensitive normalized stem for family grouping."""
    stem = strip_compound_ext(name)
    prev = None
    while prev != stem:
        prev = stem
        stem = re.sub(r"[\s_\-\.\(\[\{]*(?:v|ver|version|rev|revision)\.?\s*\d{1,4}[\s_\-\.\)\]\}]*$",
                      "", stem, flags=re.I)
        stem = re.sub(r"[\s_\-\.\(\[\{]*\(\s*\d{1,4}\s*\)[\s_\-\.\)\]\}]*$", "", stem)
        stem = re.sub(r"[\s_\-\.\(\[\{]*(?:final|finale|copy|copie|old|new|backup|sauvegarde|"
                      r"draft|brouillon|updated|modifie|modifiée|dernier|last|latest)\.?[\s_\-\.\)\]\}]*$",
                      "", stem, flags=re.I)
        stem = re.sub(r"[\s_\-\.]*" + _DATE_PATTERNS[0].pattern + r"[\s_\-\.]*$", "", stem)
        stem = re.sub(r"[\s_\-\.]*" + _DATE_PATTERNS[1].pattern + r"[\s_\-\.]*$", "", stem)
        stem = re.sub(r"[\s_\-\.\(\[\{]*\d{1,4}[\s_\-\.\)\]\}]*$", "", stem)
    tokens = re.findall(r"[0-9a-zA-ZÀ-ÖØ-öø-ÿ]+", stem.lower())
    return " ".join(tokens).strip()


def version_marker(name: str) -> dict[str, Any] | None:
    """Extract an explicit version marker (date or number), or None."""
    for idx, pat in enumerate(_DATE_PATTERNS):
        m = pat.search(name)
        if m:
            try:
                if idx == 0:
                    y, mo, d = (int(g) for g in m.groups())
                else:
                    d, mo, y = (int(g) for g in m.groups())
                return {"kind": "date", "value": f"{y:04d}-{mo:02d}-{d:02d}",
                        "sort": (y, mo, d)}
            except ValueError:
                pass
    nums = _NUM_RE.findall(strip_compound_ext(name))
    if nums:
        tail = nums[-1]
        return {"kind": "number", "value": tail, "sort": (int(tail),)}
    return None


class VersionTracker:
    def __init__(self, db: Any, store: DedupStore | None = None) -> None:
        self.db = db
        self.store = store or DedupStore(db)

    def _files(self, *, scope_prefix: str | None, include_members: bool) -> list[dict[str, Any]]:
        kinds = ["PHYSICAL_FILE", "ARCHIVE_MEMBER"] if include_members else ["PHYSICAL_FILE"]
        ph = ",".join("?" * len(kinds))
        sql = (f"SELECT id, path, filename, extension, parent_dir, size_bytes, modified_at, "
               f"document_kind, COALESCE(state,'ACTIVE') AS state "
               f"FROM files WHERE document_kind IN ({ph}) AND COALESCE(state,'ACTIVE')='ACTIVE'")
        params: list[Any] = [*kinds]
        if scope_prefix:
            sql += " AND path LIKE ? ESCAPE '\\'"
            params.append(_like_prefix(scope_prefix))
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def build(self, *, scope_prefix: str | None = None, include_members: bool = False,
              use_near_duplicates: bool = True, max_families: int = 5000) -> dict[str, Any]:
        self.store.prune_missing_relations()
        files = self._files(scope_prefix=scope_prefix, include_members=include_members)
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for f in files:
            stem = normalize_stem(f["filename"] or "")
            if not stem:
                continue
            grouped[(f.get("parent_dir") or "", stem)].append(f)

        # Optional semantic support from near-duplicate edges (evidence only).
        near_pairs: set[tuple[int, int]] = set()
        if use_near_duplicates:
            with self.db.get_connection() as conn:
                near_pairs = {(int(a), int(b)) for a, b in conn.execute(
                    "SELECT src_id, dst_id FROM near_duplicate_edges WHERE COALESCE(semantic_score,0) >= 0.9"
                ).fetchall()}

        families: list[dict[str, Any]] = []
        for (directory, stem), members in grouped.items():
            if len(members) < 2:
                continue
            markers = {int(m["id"]): version_marker(m["filename"] or "") for m in members}
            num_marked = sum(1 for mk in markers.values() if mk)
            words_present = any(_VERSION_WORDS.search(m["filename"] or "") for m in members)
            semantic_support = any(
                (int(a["id"]), int(b["id"])) in near_pairs or (int(b["id"]), int(a["id"])) in near_pairs
                for i, a in enumerate(members) for b in members[i + 1:]
            )
            if num_marked >= 2:
                confidence = "HIGH"
            elif words_present or semantic_support:
                confidence = "MEDIUM"
            else:
                confidence = "UNORDERED"
            # Chronology: explicit markers win; otherwise mtime labelled probable.
            def _order_key(m: dict[str, Any], _markers: dict[int, Any] = markers) -> tuple[Any, ...]:
                mk = _markers.get(int(m["id"]))
                if mk:
                    return (0, mk["sort"], str(m.get("modified_at") or ""))
                return (1, (), str(m.get("modified_at") or ""))

            if num_marked >= 2:
                ordered = sorted(members, key=_order_key)
                order_evidence = "explicit version marker"
            else:
                ordered = sorted(members, key=lambda m: str(m.get("modified_at") or ""))
                order_evidence = "modification time (probable)" if confidence != "UNORDERED" else "none"
            family_key = "version:" + hashlib.sha1(
                f"{directory}|{stem}".encode("utf-8", "ignore")).hexdigest()[:16]
            member_rows = []
            for rank, m in enumerate(ordered):
                member_rows.append({
                    "id": int(m["id"]), "rank": rank, "confidence": confidence,
                    "is_primary": 1 if rank == len(ordered) - 1 else 0,
                    "evidence": {"marker": markers.get(int(m["id"])), "state": m.get("state")},
                })
            families.append({
                "family_key": family_key, "base_name": stem, "directory": directory,
                "confidence": confidence, "members": member_rows,
                "evidence": {"markers": num_marked, "version_words": words_present,
                             "semantic_support": semantic_support,
                             "order": order_evidence},
            })
        families.sort(key=lambda f: len(f["members"]), reverse=True)
        families = families[:max_families]
        saved = self.store.replace_version_families(families)
        by_conf: dict[str, int] = defaultdict(int)
        for f in families:
            by_conf[f["confidence"]] += 1
        result = {"families": saved, "by_confidence": dict(by_conf),
                  "files_considered": len(files)}
        logger.info(f"version families: {result}")
        return result

    def family_for_file(self, file_id: int) -> dict[str, Any] | None:
        return self.store.get_version_family_for_file(file_id)

    def families(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return self.store.version_families(limit=limit)
