"""Evidence-based document reconstruction (M018).

Reconstruction assembles related material into an evidence pack. It never
invents missing documents or chronology:

* version ordering is claimed only when an **explicit** version marker exists;
  otherwise versions are shown unordered and the evidence is surfaced;
* a "current/final" version is flagged only when the family confidence is HIGH;
  newest mtime alone never wins;
* email threads use RFC headers only (M017), never subject text;
* archive members are listed as already indexed, never re-expanded;
* duplicates/near-duplicates reuse the canonical dedup store.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Any

from .citations import CitationRegistry
from .models import ProvenanceClass
from .privacy import mask_label, mask_text
from .provenance import build_source, file_row, has_table


@dataclass
class EvidencePack:
    kind: str
    title: str
    description: str = ""
    ordered: bool = False
    confidence: str = ProvenanceClass.UNAVAILABLE.value
    items: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diffs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "title": self.title, "description": self.description,
            "ordered": self.ordered, "confidence": self.confidence,
            "items": self.items, "relations": self.relations,
            "warnings": self.warnings, "notes": self.notes, "diffs": self.diffs,
        }


def _content(db: Any, file_id: int, *, limit: int = 4000) -> str:
    with db.get_connection() as conn:
        row = conn.execute("SELECT content_text FROM files WHERE id=?", (int(file_id),)).fetchone()
    return (row[0] or "")[:limit] if row else ""


def _header_value(text: str, name: str) -> str | None:
    for line in (text or "").splitlines()[:40]:
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
        if not line.strip():
            break
    return None


# --- version reconstruction --------------------------------------------------
def reconstruct_versions(db: Any, file_id: int, *, mode: str,
                         registry: CitationRegistry, max_items: int = 50,
                         include_diff: bool = False) -> EvidencePack:
    from ..dedup import DedupStore

    family = DedupStore(db).get_version_family_for_file(int(file_id))
    if not family:
        return EvidencePack(kind="version", title="Version family", ordered=False,
                            confidence=ProvenanceClass.UNAVAILABLE.value,
                            warnings=["no version family recorded for this document"])
    confidence = str(family.get("confidence") or "UNORDERED")
    evidence = family.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:  # noqa: BLE001
            evidence = {}
    evidence = evidence or {}
    order_evidence = str(evidence.get("order") or "none")
    # Ordered only on an explicit marker; mtime-based order is "probable" and NOT
    # presented as final.
    explicit = confidence == "HIGH" and "explicit version marker" in order_evidence
    ordered = bool(explicit)
    members = list(family.get("members") or [])[:max_items]
    items: list[dict[str, Any]] = []
    for m in members:
        fid = int(m["id"])
        row = file_row(db, fid) or {}
        src = build_source(
            registry, db, fid, mode, label=row.get("filename"),
            relations=[{"type": "VERSION_OF", "evidence": "version family membership"}],
            note=None)
        src.provenance = ProvenanceClass.DERIVED.value
        # A "current/final" version is only claimed on an explicit marker; an
        # mtime-ordered member is never presented as the final version.
        is_primary = bool(m.get("is_primary")) and explicit
        items.append({
            "ref": src.ref, "file_id": fid,
            "label": mask_label(str(row.get("filename") or f"document {fid}"), mode),
            "rank": m.get("rank") if ordered else None,
            "confidence": m.get("confidence"),
            "is_primary": is_primary,
            "primary_basis": ("explicit marker + HIGH confidence" if is_primary else None),
            "probable_order": None if explicit else "modification time (probable)",
            "size_bytes": row.get("size_bytes"), "modified_at": row.get("modified_at"),
            "state": row.get("state") or "ACTIVE",
        })
    if not ordered and confidence != "UNORDERED":
        items.sort(key=lambda i: str(i.get("modified_at") or ""))
    pack = EvidencePack(
        kind="version", title=f"Version family: {family.get('base_name') or ''}".strip(),
        description="Ordered only where an explicit version marker exists.",
        ordered=ordered, confidence=(ProvenanceClass.KNOWN.value if ordered
                                     else ProvenanceClass.INFERRED.value),
        items=items,
        relations=[{"type": "VERSION_OF", "note": "membership, not chronology"}],
        notes=[f"ordering evidence: {order_evidence}"] if order_evidence else [],
    )
    if confidence == "UNORDERED":
        pack.warnings.append("family has no ordering evidence; variants listed unordered")
    if include_diff:
        pack.diffs = _version_diffs(db, [i["file_id"] for i in items], mode)
    return pack


def _version_diffs(db: Any, file_ids: list[int], mode: str, *, max_chars: int = 2000) -> list[dict[str, Any]]:
    if len(file_ids) < 2:
        return []
    a = _content(db, file_ids[0], limit=max_chars)
    b = _content(db, file_ids[1], limit=max_chars)
    if not a or not b:
        return []
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     fromfile=f"doc-{file_ids[0]}", tofile=f"doc-{file_ids[1]}",
                                     lineterm="", n=2))
    if len(diff) > 400:
        diff = diff[:400]
    return [{"from": file_ids[0], "to": file_ids[1],
             "text": mask_text("\n".join(diff), mode), "bounded": len(diff) >= 400}]


# --- email thread reconstruction ---------------------------------------------
def reconstruct_email_thread(db: Any, file_id: int, *, mode: str,
                             registry: CitationRegistry, max_items: int = 200) -> EvidencePack:
    if not has_table(db, "email_threads"):
        return EvidencePack(kind="email_thread", title="Email thread",
                            confidence=ProvenanceClass.UNAVAILABLE.value,
                            warnings=["email threading unavailable (M017 table absent)"])
    with db.get_connection() as conn:
        row = conn.execute("SELECT thread_key FROM email_threads WHERE file_id=?",
                           (int(file_id),)).fetchone()
        if row is None or not row[0]:
            return EvidencePack(kind="email_thread", title="Email thread",
                                confidence=ProvenanceClass.UNAVAILABLE.value,
                                warnings=["no RFC-header thread recorded for this message"])
        thread_key = row[0]
        rows = [dict(r) for r in conn.execute(
            "SELECT t.file_id AS id, t.message_id, t.in_reply_to, t.references_text, "
            "t.subject, t.date, f.filename, f.path, f.modified_at, COALESCE(f.state,'ACTIVE') AS state "
            "FROM email_threads t JOIN files f ON f.id=t.file_id WHERE t.thread_key=? "
            "ORDER BY COALESCE(t.date, f.modified_at) ASC, t.file_id ASC LIMIT ?",
            (thread_key, int(max_items))).fetchall()]
    items: list[dict[str, Any]] = []
    for r in rows:
        fid = int(r["id"])
        src = build_source(registry, db, fid, mode, label=r.get("filename"),
                           relations=[{"type": "EMAIL_REPLY_TO",
                                       "evidence": "RFC headers (Message-ID/In-Reply-To/References)"}])
        body = _content(db, fid, limit=2000)
        sender = _header_value(body, "From")
        recipient = _header_value(body, "To")
        date = r.get("date") or r.get("modified_at")
        items.append({
            "ref": src.ref, "file_id": fid,
            "subject": mask_label(str(r.get("subject") or "(no subject)"), mode),
            "sender": mask_label(sender, mode) if sender else None,
            "recipient": mask_label(recipient, mode) if recipient else None,
            "sender_provenance": ProvenanceClass.KNOWN.value if sender else ProvenanceClass.UNAVAILABLE.value,
            "message_id": r.get("message_id"), "in_reply_to": r.get("in_reply_to"),
            "date": str(date)[:19] if date else None,
            "date_source": "email_header" if r.get("date") else "modified_at",
            "attachments": "metadata only (see extraction)",
        })
    return EvidencePack(
        kind="email_thread", title=f"Email thread ({len(items)} messages)",
        description="Reply edges come from RFC headers only; no subject-based inference.",
        ordered=True, confidence=ProvenanceClass.KNOWN.value, items=items,
        relations=[{"type": "EMAIL_REPLY_TO", "note": "directed, header evidence"}])


# --- archive reconstruction --------------------------------------------------
def reconstruct_archive(db: Any, parent_id: int, *, mode: str,
                        registry: CitationRegistry, max_items: int = 500) -> EvidencePack:
    row = file_row(db, parent_id)
    if row is None:
        return EvidencePack(kind="archive", title="Archive package",
                            confidence=ProvenanceClass.UNAVAILABLE.value,
                            warnings=["archive parent not found"])
    parent_ref = build_source(registry, db, parent_id, mode, label=row.get("filename"))
    members = db.get_archive_members(int(parent_id), include_missing=True, limit=max_items)
    items: list[dict[str, Any]] = []
    for m in members:
        fid = int(m["id"])
        src = build_source(registry, db, fid, mode,
                           label=m.get("archive_member_path") or m.get("filename"),
                           relations=[{"type": "ARCHIVE_CONTAINS",
                                       "evidence": "archive membership"}])
        state = m.get("member_state") or m.get("state") or "ACTIVE"
        items.append({"ref": src.ref, "file_id": fid,
                      "member_path": m.get("archive_member_path") or m.get("filename"),
                      "state": state, "size_bytes": m.get("member_uncompressed_size") or m.get("size_bytes"),
                      "extraction_state": m.get("extraction_state")})
    warnings = []
    if len(members) >= max_items:
        warnings.append(f"member list truncated at {max_items}")
    return EvidencePack(
        kind="archive", title=f"Archive package: {row.get('filename')}",
        description="Members are listed as indexed; the archive is not re-expanded.",
        ordered=True, confidence=ProvenanceClass.DERIVED.value,
        items=items, relations=[{"type": "ARCHIVE_CONTAINS", "parent_ref": parent_ref.ref}],
        warnings=warnings)


# --- duplicate reconstruction ------------------------------------------------
def _exact_group_members(db: Any, file_id: int, *, limit: int = 100) -> tuple[str | None, list[dict[str, Any]]]:
    if not has_table(db, "content_hashes"):
        return None, []
    with db.get_connection() as conn:
        row = conn.execute("SELECT digest FROM content_hashes WHERE file_id=? AND state='OK'",
                           (int(file_id),)).fetchone()
        if row is None or not row[0]:
            return None, []
        digest = row[0]
        members = [dict(r) for r in conn.execute(
            "SELECT f.id, f.filename, f.path, f.size_bytes, COALESCE(f.state,'ACTIVE') AS state "
            "FROM content_hashes h JOIN files f ON f.id=h.file_id "
            "WHERE h.state='OK' AND h.digest=? AND COALESCE(f.state,'ACTIVE')='ACTIVE' "
            "ORDER BY f.path ASC LIMIT ?", (digest, int(limit))).fetchall()]
        return digest, members


def reconstruct_duplicates(db: Any, file_id: int, *, mode: str,
                           registry: CitationRegistry, max_items: int = 100) -> EvidencePack:
    from ..dedup import DedupStore

    digest, exact = _exact_group_members(db, file_id, limit=max_items)
    near = DedupStore(db).near_duplicates_for(int(file_id), limit=max_items)
    items: list[dict[str, Any]] = []
    seen: set[int] = {int(file_id)}
    for m in exact:
        if int(m["id"]) in seen:
            continue
        seen.add(int(m["id"]))
        src = build_source(registry, db, int(m["id"]), mode, label=m.get("filename"),
                           relations=[{"type": "EXACT_DUPLICATE", "evidence": f"sha256:{digest}"}])
        items.append({"ref": src.ref, "file_id": int(m["id"]),
                      "relationship": "EXACT_DUPLICATE", "evidence": f"sha256:{digest}",
                      "confidence": ProvenanceClass.KNOWN.value})
    for n in near:
        fid = int(n.get("id") or n.get("file_id") or 0)
        if not fid or fid in seen:
            continue
        seen.add(fid)
        src = build_source(registry, db, fid, mode, label=n.get("filename"))
        items.append({"ref": src.ref, "file_id": fid, "relationship": "NEAR_DUPLICATE",
                      "evidence": {"score": n.get("score") or n.get("similarity")},
                      "confidence": ProvenanceClass.DERIVED.value})
    return EvidencePack(
        kind="duplicates", title="Duplicate / version group",
        description="Exact duplicates by content hash; near-duplicates by the canonical dedup store.",
        ordered=False, confidence=ProvenanceClass.DERIVED.value, items=items,
        relations=[{"type": "EXACT_DUPLICATE"}, {"type": "NEAR_DUPLICATE"}])


# --- timeline reconstruction -------------------------------------------------
def reconstruct_timeline(db: Any, *, start: str | None = None, end: str | None = None,
                         source: str = "modified_at", scope_prefix: str | None = None,
                         mode: str = "FULL_LOCAL", registry: CitationRegistry,
                         max_items: int = 500) -> EvidencePack:
    from ..graph.timeline import TimelineService

    result = TimelineService(db).events(start=start, end=end, source=source,
                                        scope_prefix=scope_prefix, limit=max_items)
    items: list[dict[str, Any]] = []
    for ev in result.get("events", []):
        fid = int(ev.get("file_id") or ev.get("id"))
        src = build_source(registry, db, fid, mode, label=ev.get("filename"))
        items.append({"ref": src.ref, "file_id": fid, "date": ev.get("date"),
                      "date_source": ev.get("date_source"), "confidence": ev.get("confidence"),
                      "date_meaning": ev.get("date_meaning") or ev.get("provenance")})
    return EvidencePack(
        kind="timeline", title="Timeline", ordered=True,
        confidence=result.get("confidence") or ProvenanceClass.DERIVED.value,
        items=items, notes=[f"date source: {result.get('provenance') or source}"])
