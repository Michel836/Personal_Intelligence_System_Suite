"""Mono-user dossiers / projects (M018).

A dossier is a *view* over the canonical ``files`` table, never a copy.

* **STATIC**  — a frozen, explicitly ordered document set.
* **DYNAMIC** — resolved from a saved query/filter at read time; the current
  match count, last refresh, and the added/removed/ missing delta are always
  exposed. Freezing stores a snapshot for comparison.

Manual membership always wins: manually added documents are pinned even when the
dynamic query would not match them, and explicitly excluded documents stay out.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .models import DossierMode
from .store import ReportStore


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def new_dossier_id() -> str:
    return "dos_" + uuid.uuid4().hex[:12]


def run_query(db: Any, query: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a saved/dynamic dossier query through the canonical search."""
    query = dict(query or {})
    kwargs: dict[str, Any] = {}
    for key in ("extension", "document_kind", "language", "category",
                "entity_type", "entity_value"):
        if query.get(key):
            kwargs[key] = query[key]
    if query.get("has_pii") is not None:
        kwargs["has_pii"] = bool(query["has_pii"])
    if query.get("exclude_high_sensitivity"):
        kwargs["exclude_high_sensitivity"] = True
    if query.get("include_missing"):
        kwargs["include_missing"] = True
    limit = int(query.get("limit") or 200)
    text = query.get("query")
    rows = db.search_files(text, limit=limit, **kwargs)
    return [dict(r) for r in rows]


def _query_fingerprint(query: dict[str, Any]) -> str:
    blob = json.dumps(query or {}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class DossierService:
    def __init__(self, db: Any, *, store: ReportStore | None = None) -> None:
        self.db = db
        self.store = store or ReportStore(db)

    # -- CRUD --------------------------------------------------------------
    def create(self, name: str, *, description: str = "",
               mode: str = DossierMode.STATIC.value,
               query: dict[str, Any] | None = None,
               file_ids: list[int] | None = None) -> dict[str, Any]:
        dossier_id = new_dossier_id()
        self.store.create_dossier(dossier_id, name, description=description,
                                  mode=mode, query=query)
        if file_ids:
            self.store.add_documents(dossier_id, file_ids)
        return self.store.get_dossier(dossier_id) or {}

    def get(self, dossier_id: str) -> dict[str, Any] | None:
        return self.store.get_dossier(dossier_id)

    def list_dossiers(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.list_dossiers(limit=limit)

    def rename(self, dossier_id: str, name: str, *, description: str | None = None) -> None:
        self.store.rename_dossier(dossier_id, name, description=description)

    def delete(self, dossier_id: str) -> None:
        self.store.delete_dossier(dossier_id)

    # -- membership --------------------------------------------------------
    def add_documents(self, dossier_id: str, file_ids: list[int], **kwargs: Any) -> int:
        return self.store.add_documents(dossier_id, file_ids, **kwargs)

    def remove_documents(self, dossier_id: str, file_ids: list[int]) -> int:
        return self.store.remove_documents(dossier_id, file_ids)

    def exclude_documents(self, dossier_id: str, file_ids: list[int]) -> int:
        """Pin documents *out* of a dynamic dossier (manual exclusion wins)."""
        if not file_ids:
            return 0
        now = _now_iso()
        with self.db.get_connection() as conn:
            for fid in file_ids:
                conn.execute(
                    """INSERT INTO dossier_documents
                           (dossier_id, file_id, position, section, note, manual, added_at)
                       VALUES (?, ?, 0, NULL, NULL, -1, ?)
                       ON CONFLICT(dossier_id, file_id) DO UPDATE SET manual=-1""",
                    (dossier_id, int(fid), now))
            conn.execute("UPDATE dossiers SET updated_at=? WHERE dossier_id=?",
                         (now, dossier_id))
            conn.commit()
        return len(file_ids)

    def reorder(self, dossier_id: str, ordered_ids: list[int]) -> None:
        self.store.reorder_documents(dossier_id, ordered_ids)

    def set_note(self, dossier_id: str, file_id: int, note: str) -> None:
        self.store.set_member_note(dossier_id, file_id, note)

    def add_section(self, dossier_id: str, title: str) -> int:
        return self.store.add_section(dossier_id, title)

    def remove_section(self, dossier_id: str, section_id: int) -> None:
        self.store.remove_section(dossier_id, section_id)

    def create_from_query(self, name: str, query: dict[str, Any], *,
                          mode: str = DossierMode.DYNAMIC.value,
                          description: str = "") -> dict[str, Any]:
        return self.create(name, description=description, mode=mode, query=query)

    # -- resolution --------------------------------------------------------
    def resolve(self, dossier_id: str, *, limit: int = 5000) -> dict[str, Any]:
        dossier = self.store.get_dossier(dossier_id)
        if dossier is None:
            return {"dossier_id": dossier_id, "members": [], "count": 0, "missing": 0,
                    "mode": None, "error": "dossier not found"}
        mode = dossier.get("mode") or DossierMode.STATIC.value
        rows = dossier.get("members") or []
        includes = [r for r in rows if int(r.get("manual", 1)) == 1]
        excludes = {int(r["file_id"]) for r in rows if int(r.get("manual", 1)) == -1}

        ordered: list[dict[str, Any]] = []
        seen: set[int] = set()
        if mode == DossierMode.DYNAMIC.value:
            for qr in run_query(self.db, dossier.get("query") or {}):
                fid = int(qr["id"])
                if fid in excludes or fid in seen:
                    continue
                seen.add(fid)
                ordered.append(self._member(fid, source="query"))
        for r in includes:
            fid = int(r["file_id"])
            if fid in seen:
                # Manual pin refines an already-matched doc: keep manual metadata.
                for m in ordered:
                    if m["file_id"] == fid:
                        m.update({"source": "manual", "note": r.get("note"),
                                  "section": r.get("section"),
                                  "position": r.get("position")})
                continue
            seen.add(fid)
            ordered.append(self._member(fid, source="manual", note=r.get("note"),
                                        section=r.get("section"), position=r.get("position")))
        # Manual positions sort before query-only matches when present.
        if any(m["source"] == "manual" for m in ordered):
            ordered.sort(key=lambda m: (0 if m["source"] == "manual" else 1,
                                        m.get("position") if m.get("position") is not None else 10**9))
        members = ordered[: int(limit)]
        missing = sum(1 for m in members if m.get("state") != "ACTIVE")
        return {"dossier_id": dossier_id, "name": dossier.get("name"),
                "mode": mode, "members": members, "count": len(members),
                "missing": missing, "query": dossier.get("query") or {},
                "frozen": dossier.get("frozen")}

    def _member(self, file_id: int, *, source: str, note: str | None = None,
                section: str | None = None, position: Any = None) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT id, filename, path, extension, document_kind, "
                "COALESCE(state,'ACTIVE') AS state FROM files WHERE id=?",
                (int(file_id),)).fetchone()
        if row is None:
            return {"file_id": int(file_id), "filename": None, "state": "MISSING",
                    "source": source, "note": note, "section": section,
                    "position": position, "missing": True}
        out = dict(row)
        out["file_id"] = int(out.pop("id"))
        out.update({"source": source, "note": note, "section": section,
                    "position": position, "missing": out.get("state") != "ACTIVE"})
        return out

    def member_ids(self, dossier_id: str) -> list[int]:
        return [int(m["file_id"]) for m in self.resolve(dossier_id)["members"]]

    # -- dynamic refresh / snapshot ---------------------------------------
    def refresh_preview(self, dossier_id: str) -> dict[str, Any]:
        resolved = self.resolve(dossier_id)
        current = [int(m["file_id"]) for m in resolved["members"]]
        frozen = resolved.get("frozen")
        out: dict[str, Any] = {
            "dossier_id": dossier_id, "mode": resolved.get("mode"),
            "current_count": len(current), "missing": resolved.get("missing", 0),
            "query_fingerprint": _query_fingerprint(resolved.get("query") or {}),
            "last_refresh": _now_iso(), "frozen": bool(frozen),
        }
        if frozen:
            frozen_ids = [int(i) for i in frozen.get("ids", [])]
            added = [i for i in current if i not in set(frozen_ids)]
            removed = [i for i in frozen_ids if i not in set(current)]
            out.update({"added_since_snapshot": added, "removed_since_snapshot": removed,
                        "snapshot_at": frozen.get("at"),
                        "snapshot_count": len(frozen_ids)})
        return out

    def freeze(self, dossier_id: str) -> dict[str, Any]:
        ids = self.member_ids(dossier_id)
        fingerprint = hashlib.sha256(",".join(str(i) for i in ids).encode()).hexdigest()
        self.store.freeze(dossier_id, ids, fingerprint=fingerprint)
        return {"dossier_id": dossier_id, "frozen_count": len(ids),
                "fingerprint": fingerprint, "at": _now_iso()}

    def unfreeze(self, dossier_id: str) -> None:
        self.store.unfreeze(dossier_id)

    def compare_snapshot(self, dossier_id: str) -> dict[str, Any]:
        resolved = self.resolve(dossier_id)
        frozen = resolved.get("frozen")
        if not frozen:
            return {"dossier_id": dossier_id, "has_snapshot": False}
        current = [int(m["file_id"]) for m in resolved["members"]]
        frozen_ids = [int(i) for i in frozen.get("ids", [])]
        current_set = set(current)
        frozen_set = set(frozen_ids)
        added = [i for i in current if i not in frozen_set]
        removed = [i for i in frozen_ids if i not in current_set]
        return {"dossier_id": dossier_id, "has_snapshot": True,
                "snapshot_at": frozen.get("at"), "snapshot_count": len(frozen_ids),
                "current_count": len(current), "added": added, "removed": removed,
                "unchanged": len(current_set & frozen_set)}
