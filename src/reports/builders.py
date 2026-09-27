"""Report content assembly (M018).

Each report type is assembled from **canonical services** — lexical search,
dedup, graph/timeline, intel, ingest — into the renderer-agnostic IR. No report
type re-implements business logic and none keeps its own copy of documents.
"""
from __future__ import annotations

import re
from typing import Any

from loguru import logger

from .citations import CitationRegistry
from .models import (
    Block,
    BlockType,
    PrivacyMode,
    ProvenanceClass,
    ReportDefinition,
    ReportIR,
    ReportKind,
    Section,
)
from .privacy import (
    banner,
    describe_mode,
    filter_documents,
    includes_content,
    is_high_sensitivity,
    mask_label,
    mask_text,
)
from .provenance import build_source, file_row, has_table


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or fallback


def _row_value(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if row.get(k) is not None:
            return row[k]
    return default


class ReportBuilder:
    def __init__(self, db: Any, *, reconstructor: dict[str, Any] | None = None) -> None:
        self.db = db
        self._r: dict[str, Any]
        if reconstructor is None:
            from .reconstruction import (
                reconstruct_archive,
                reconstruct_duplicates,
                reconstruct_email_thread,
                reconstruct_timeline,
                reconstruct_versions,
            )
            self._r = {
                "version": reconstruct_versions,
                "email_thread": reconstruct_email_thread,
                "archive": reconstruct_archive,
                "duplicates": reconstruct_duplicates,
                "timeline": reconstruct_timeline,
            }
        else:
            self._r = reconstructor

    # -- entry point -------------------------------------------------------
    def build(self, definition: ReportDefinition) -> ReportIR:
        ir = ReportIR(definition=definition)
        try:
            builder = {
                ReportKind.SEARCH.value: self._build_search,
                ReportKind.DOSSIER.value: self._build_dossier,
                ReportKind.TIMELINE.value: self._build_timeline,
                ReportKind.DUPLICATES.value: self._build_duplicates,
                ReportKind.ENTITY_CATEGORY.value: self._build_entity_category,
                ReportKind.PII_SUMMARY.value: self._build_pii_summary,
                ReportKind.INGESTION.value: self._build_ingestion,
                ReportKind.PROJECT.value: self._build_project,
            }.get(definition.kind)
            if builder is None:
                ir.warnings.append(f"unknown report kind: {definition.kind}")
                return ir
            builder(definition, ir)
        except Exception as exc:  # noqa: BLE001 - one bad report must not crash the app
            logger.exception("M018 report assembly failed")
            ir.warnings.append(f"assembly error: {type(exc).__name__}")
        ir.stats.setdefault("source_count", len(ir.sources))
        ir.stats.setdefault("section_count", len(ir.sections))
        return ir

    # -- shared helpers ----------------------------------------------------
    def _collect_ids(self, definition: ReportDefinition, *, limit: int) -> list[int]:
        if definition.document_ids:
            return [int(i) for i in definition.document_ids][:limit]
        query = definition.query or {}
        kwargs: dict[str, Any] = {}
        for key in ("extension", "document_kind", "language", "category",
                    "entity_type", "entity_value"):
            if query.get(key):
                kwargs[key] = query[key]
        if query.get("has_pii") is not None:
            kwargs["has_pii"] = bool(query["has_pii"])
        if query.get("exclude_high_sensitivity"):
            kwargs["exclude_high_sensitivity"] = True
        rows = self.db.search_files(query.get("query"), limit=limit, **kwargs)
        return [int(r["id"]) for r in rows]

    def _rows_by_id(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        return {int(i): (file_row(self.db, int(i)) or {}) for i in ids}

    def _apply_privacy(self, definition: ReportDefinition, ids: list[int],
                       ir: ReportIR) -> list[int]:
        kept, omitted = filter_documents(self.db, ids, definition.privacy_mode)
        if omitted:
            ir.omitted.extend(omitted)
            ir.warnings.append(
                f"{len(omitted)} document(s) omitted by privacy mode "
                f"{definition.privacy_mode}")
        # Never export a sensitive document under FULL_LOCAL without a warning.
        if definition.privacy_mode == PrivacyMode.FULL_LOCAL.value and kept:
            sensitive = sum(1 for fid in kept[:500] if is_high_sensitivity(self.db, fid))
            if sensitive:
                ir.warnings.append(
                    f"{sensitive} included document(s) contain high-severity PII; "
                    "consider MASK_PII or OMIT_HIGH_SENSITIVITY")
        return kept

    def _card(self, registry: CitationRegistry, definition: ReportDefinition,
              fid: int, *, score: float | None = None,
              relations: list[dict[str, Any]] | None = None,
              note: str | None = None) -> dict[str, Any]:
        src = build_source(registry, self.db, fid, definition.privacy_mode,
                           score=score, relations=relations, note=note)
        row = file_row(self.db, fid) or {}
        return {
            "ref": src.ref, "file_id": fid,
            "label": src.label, "path": src.path, "date": src.date,
            "date_source": src.date_source, "date_class": src.date_class,
            "extraction_state": src.extraction_state,
            "state": row.get("state") or "ACTIVE", "score": src.score,
            "relations": src.relations, "note": src.note,
        }

    def _results_table(self, definition: ReportDefinition, registry: CitationRegistry,
                       ids: list[int], rows: dict[int, dict[str, Any]]) -> Block:
        table_rows: list[list[Any]] = []
        for fid in ids:
            src = registry.ref_for_document(fid)
            if src is None:
                src = build_source(registry, self.db, fid, definition.privacy_mode).ref
            row = rows.get(fid, {})
            table_rows.append([
                src,
                mask_label(str(row.get("filename") or f"document {fid}"), definition.privacy_mode),
                row.get("extension") or "", row.get("modified_at") or "",
                row.get("size_bytes") or "", row.get("state") or "ACTIVE",
            ])
        return Block(BlockType.TABLE.value, {
            "columns": ["Ref", "Document", "Ext", "Modified", "Bytes", "State"],
            "rows": table_rows, "caption": "Included documents",
        })

    def _cards_section(self, definition: ReportDefinition, registry: CitationRegistry,
                       ids: list[int], *, title: str = "Document provenance") -> Section:
        blocks = [Block(BlockType.DOCUMENT_CARD.value, self._card(registry, definition, fid))
                  for fid in ids]
        return Section(id="documents", title=title, blocks=blocks,
                       provenance=ProvenanceClass.KNOWN.value)

    def _content_excerpt(self, fid: int, limit: int = 400) -> str:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT content_text FROM files WHERE id=?", (int(fid),)).fetchone()
        return (row[0] or "")[:limit] if row else ""

    def _excerpts_section(self, definition: ReportDefinition, registry: CitationRegistry,
                          ids: list[int], *, title: str = "Document excerpts",
                          per_doc: int = 400) -> Section | None:
        if not includes_content(definition.privacy_mode):
            return None
        blocks: list[Block] = []
        for fid in ids:
            text = mask_text(self._content_excerpt(fid, per_doc), definition.privacy_mode).strip()
            if not text:
                continue
            ref = registry.ref_for_document(fid) or build_source(
                registry, self.db, fid, definition.privacy_mode).ref
            blocks.append(Block(BlockType.PARAGRAPH.value, {"text": text, "citations": [ref]}))
        if not blocks:
            return None
        return Section(id="excerpts", title=title, blocks=blocks,
                       provenance=ProvenanceClass.KNOWN.value)

    def _base_metadata(self, definition: ReportDefinition, extra: dict[str, Any] | None = None) -> Block:
        desc = describe_mode(definition.privacy_mode)
        items = {
            "report id": definition.report_id,
            "kind": definition.kind,
            "privacy mode": f"{desc.get('label')} ({definition.privacy_mode})",
            "privacy banner": banner(definition.privacy_mode),
        }
        items.update(extra or {})
        return Block(BlockType.METADATA.value, {"items": items})

    # -- report types ------------------------------------------------------
    def _build_search(self, definition: ReportDefinition, ir: ReportIR) -> None:
        query = definition.query or {}
        limit = int(definition.options.get("limit") or query.get("limit") or 100)
        ids = self._apply_privacy(definition, self._collect_ids(definition, limit=limit), ir)
        registry = CitationRegistry()
        rows = self._rows_by_id(ids)
        q = query.get("query")
        overview = (f"Search report for query {q!r}." if q else "Search report over all indexed documents.")
        ir.sections.append(Section(id="overview", title="Overview", blocks=[
            self._base_metadata(definition, {"query": q or "(all)", "matched": len(ids)}),
            Block(BlockType.PARAGRAPH.value, {"text": overview}),
        ]))
        ir.sections.append(Section(id="results", title="Results", blocks=[
            self._results_table(definition, registry, ids, rows)]))
        if ids:
            ir.sections.append(self._cards_section(definition, registry, ids))
            if definition.options.get("excerpts", True):
                excerpts = self._excerpts_section(definition, registry, ids)
                if excerpts is not None:
                    ir.sections.append(excerpts)
        ir.sources = registry.sources()
        ir.stats.update({"matched": len(ids)})

    def _build_dossier(self, definition: ReportDefinition, ir: ReportIR) -> None:
        from .dossiers import DossierService
        dossier_id = definition.options.get("dossier_id")
        if not dossier_id:
            ir.warnings.append("dossier report without dossier_id")
            return
        resolved = DossierService(self.db).resolve(dossier_id)
        if resolved.get("error"):
            ir.warnings.append(resolved["error"])
            return
        ids = self._apply_privacy(definition, [int(m["file_id"]) for m in resolved["members"]], ir)
        registry = CitationRegistry()
        rows = self._rows_by_id(ids)
        ir.sections.append(Section(id="overview", title="Dossier overview", blocks=[
            self._base_metadata(definition, {
                "dossier": resolved.get("name"), "mode": resolved.get("mode"),
                "members": resolved.get("count"), "missing": resolved.get("missing"),
            }),
            Block(BlockType.PARAGRAPH.value, {
                "text": f"Dossier {resolved.get('name')!r} contains {resolved.get('count')} "
                        f"member(s) ({resolved.get('mode')} mode)."}),
        ]))
        by_section: dict[str, list[int]] = {}
        for member in resolved["members"]:
            fid = int(member["file_id"])
            if fid not in rows:
                continue
            by_section.setdefault(str(member.get("section") or ""), []).append(fid)
        idx = 0
        for title, section_ids in by_section.items():
            idx += 1
            heading = title or "Members"
            section = self._cards_section(definition, registry, section_ids,
                                          title=f"{idx}. {heading}")
            section.id = f"sec-{idx}-{_slug(heading, str(idx))}"
            ir.sections.append(section)
            if definition.options.get("excerpts", True):
                excerpts = self._excerpts_section(definition, registry, section_ids,
                                                  title=f"Excerpts — {heading}")
                if excerpts is not None:
                    ir.sections.append(excerpts)
        ir.sources = registry.sources()
        ir.stats.update({"members": resolved.get("count")})

    def _build_project(self, definition: ReportDefinition, ir: ReportIR) -> None:
        ids = self._apply_privacy(definition, self._collect_ids(definition, limit=500), ir)
        registry = CitationRegistry()
        rows = self._rows_by_id(ids)
        sections = definition.options.get("sections") or []
        ir.sections.append(Section(id="overview", title="Project overview", blocks=[
            self._base_metadata(definition, {"documents": len(ids)}),
            Block(BlockType.PARAGRAPH.value, {"text": definition.description or "Custom dossier."}),
        ]))
        if sections:
            for i, spec in enumerate(sections, start=1):
                member_ids = [int(x) for x in spec.get("document_ids", []) if int(x) in rows]
                title = str(spec.get("title") or f"Section {i}")
                sec = self._cards_section(definition, registry, member_ids or ids,
                                          title=title)
                sec.id = f"sec-{i}-{_slug(title, str(i))}"
                ir.sections.append(sec)
        else:
            ir.sections.append(self._cards_section(definition, registry, ids))
        ir.sections.append(Section(id="results", title="All documents", blocks=[
            self._results_table(definition, registry, ids, rows)]))
        ir.sources = registry.sources()
        ir.stats.update({"documents": len(ids)})

    def _build_timeline(self, definition: ReportDefinition, ir: ReportIR) -> None:
        query = definition.query or {}
        registry = CitationRegistry()
        pack = self._r["timeline"](
            self.db, start=query.get("start"), end=query.get("end"),
            source=query.get("source") or "modified_at",
            scope_prefix=query.get("scope_prefix"),
            mode=definition.privacy_mode, registry=registry,
            max_items=int(definition.options.get("limit") or 500))
        ir.sections.append(Section(id="overview", title="Timeline overview", blocks=[
            self._base_metadata(definition, {
                "range": f"{query.get('start') or '…'} → {query.get('end') or '…'}",
                "date source": query.get("source") or "modified_at",
                "events": len(pack.items), "confidence": pack.confidence}),
            Block(BlockType.PARAGRAPH.value, {
                "text": f"{len(pack.items)} event(s); date confidence {pack.confidence}."}),
        ]))
        ir.sections.append(Section(id="timeline", title="Chronology", blocks=[
            Block(BlockType.TIMELINE.value, {"events": pack.items})]))
        ir.sources = registry.sources()
        ir.warnings.extend(pack.warnings)
        ir.stats.update({"events": len(pack.items), "date_confidence": pack.confidence})

    def _build_duplicates(self, definition: ReportDefinition, ir: ReportIR) -> None:
        registry = CitationRegistry()
        ids = self._apply_privacy(definition, definition.document_ids, ir)
        if ids:
            ir.sections.append(Section(id="overview", title="Duplicate overview", blocks=[
                self._base_metadata(definition, {"documents": len(ids)})]))
            for i, fid in enumerate(ids, start=1):
                pack = self._r["duplicates"](self.db, fid, mode=definition.privacy_mode,
                                             registry=registry,
                                             max_items=int(definition.options.get("limit") or 100))
                section = Section(id=f"group-{i}", title=pack.title, blocks=[
                    Block(BlockType.PARAGRAPH.value, {"text": pack.description}),
                    Block(BlockType.TABLE.value, {
                        "columns": ["Ref", "Relationship", "Evidence", "Confidence"],
                        "rows": [[it["ref"], it["relationship"], str(it.get("evidence")), it.get("confidence")]
                                 for it in pack.items]}),
                ], provenance=pack.confidence)
                ir.sections.append(section)
                ir.warnings.extend(pack.warnings)
        else:
            from ..dedup import DedupStore
            groups = DedupStore(self.db).exact_duplicate_groups(
                min_size=int(definition.options.get("min_size") or 1),
                max_groups=int(definition.options.get("max_groups") or 100),
                max_members_per_group=int(definition.options.get("max_members") or 50))
            ir.sections.append(Section(id="overview", title="Duplicate overview", blocks=[
                self._base_metadata(definition, {"groups": len(groups)}),
                Block(BlockType.PARAGRAPH.value, {
                    "text": f"{len(groups)} exact-duplicate group(s) by content hash."})]))
            table_rows = []
            for g in groups:
                refs = []
                for m in g.get("members", []):
                    sid = build_source(registry, self.db, int(m["id"]),
                                       definition.privacy_mode, label=m.get("filename"))
                    refs.append(sid.ref)
                table_rows.append([refs[0] if refs else "-", len(g.get("members", [])),
                                   g.get("size_bytes"), g.get("wasted_bytes")])
            ir.sections.append(Section(id="groups", title="Exact duplicate groups", blocks=[
                Block(BlockType.TABLE.value, {
                    "columns": ["Representative", "Members", "Bytes each", "Wasted bytes"],
                    "rows": table_rows})], provenance=ProvenanceClass.DERIVED.value))
        ir.sources = registry.sources()

    def _build_entity_category(self, definition: ReportDefinition, ir: ReportIR) -> None:
        query = definition.query or {}
        limit = int(definition.options.get("limit") or query.get("limit") or 200)
        ids = self._apply_privacy(definition, self._collect_ids(definition, limit=limit), ir)
        registry = CitationRegistry()
        rows = self._rows_by_id(ids)
        label = query.get("category") or query.get("entity_value") or "(filter)"
        ir.sections.append(Section(id="overview", title="Selection", blocks=[
            self._base_metadata(definition, {
                "category": query.get("category"),
                "entity": f"{query.get('entity_type')}={query.get('entity_value')}"
                          if query.get("entity_type") else None,
                "matched": len(ids)}),
            Block(BlockType.PARAGRAPH.value, {
                "text": f"{len(ids)} document(s) matching {label}."})]))
        ir.sections.append(Section(id="results", title="Documents", blocks=[
            self._results_table(definition, registry, ids, rows)]))
        if ids:
            ir.sections.append(self._cards_section(definition, registry, ids,
                                                   title="Document provenance"))
        ir.sources = registry.sources()
        ir.stats.update({"matched": len(ids)})

    def _build_pii_summary(self, definition: ReportDefinition, ir: ReportIR) -> None:
        query = definition.query or {}
        scope_doc_ids = [int(i) for i in (definition.document_ids or [])]
        registry = CitationRegistry()
        if not has_table(self.db, "doc_pii"):
            ir.warnings.append("PII summary unavailable: intelligence tables absent")
            ir.sections.append(Section(id="overview", title="PII overview", blocks=[
                self._base_metadata(definition, {"classes": 0, "documents_with_pii": 0})]))
            return
        with self.db.get_connection() as conn:
            if scope_doc_ids:
                ph = ",".join("?" * len(scope_doc_ids))
                summary = [dict(r) for r in conn.execute(
                    f"SELECT pii_type, severity, COUNT(DISTINCT file_id) AS docs, SUM(count) AS hits "
                    f"FROM doc_pii WHERE file_id IN ({ph}) GROUP BY pii_type, severity "
                    f"ORDER BY docs DESC", scope_doc_ids).fetchall()]
                doc_rows = [dict(r) for r in conn.execute(
                    f"SELECT file_id, MAX(CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 "
                    f"WHEN 'low' THEN 1 ELSE 0 END) AS sev FROM doc_pii WHERE file_id IN ({ph}) "
                    f"GROUP BY file_id ORDER BY sev DESC LIMIT 200", scope_doc_ids).fetchall()]
            else:
                conditions = []
                params: list[Any] = []
                if query.get("exclude_high_sensitivity"):
                    conditions.append("severity != 'high'")
                where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
                summary = [dict(r) for r in conn.execute(
                    f"SELECT pii_type, severity, COUNT(DISTINCT file_id) AS docs, SUM(count) AS hits "
                    f"FROM doc_pii{where} GROUP BY pii_type, severity ORDER BY docs DESC",
                    params).fetchall()]
                doc_rows = [dict(r) for r in conn.execute(
                    "SELECT file_id, MAX(CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 "
                    "WHEN 'low' THEN 1 ELSE 0 END) AS sev FROM doc_pii "
                    "GROUP BY file_id ORDER BY sev DESC LIMIT 200").fetchall()]
        ir.sections.append(Section(id="overview", title="PII overview", blocks=[
            self._base_metadata(definition, {
                "classes": len(summary),
                "documents_with_pii": len(doc_rows)}),
            Block(BlockType.PARAGRAPH.value, {
                "text": "Aggregate PII classification. Only masked values and fingerprints "
                        "are stored; no raw identifiers appear in this report."})]))
        ir.sections.append(Section(id="by-type", title="Findings by type", blocks=[
            Block(BlockType.TABLE.value, {
                "columns": ["Type", "Severity", "Documents", "Occurrences"],
                "rows": [[s["pii_type"], s["severity"], s["docs"], s["hits"]] for s in summary]})],
            provenance=ProvenanceClass.DERIVED.value))
        doc_ids = self._apply_privacy(definition, [int(r["file_id"]) for r in doc_rows], ir)
        rows = self._rows_by_id(doc_ids)
        ir.sections.append(Section(id="documents", title="Documents by sensitivity", blocks=[
            self._results_table(definition, registry, doc_ids, rows)]))
        ir.sources = registry.sources()
        ir.stats.update({"pii_classes": len(summary), "documents_with_pii": len(doc_ids)})

    def _build_ingestion(self, definition: ReportDefinition, ir: ReportIR) -> None:
        from ..ingest.capabilities import capability_matrix
        from ..ingest.queue_store import ExtractionQueue
        queue = ExtractionQueue(self.db)
        stats = queue.stats()
        issues = queue.issues(limit=int(definition.options.get("limit") or 200))
        ir.sections.append(Section(id="overview", title="Extraction health", blocks=[
            self._base_metadata(definition, {
                "queued": stats.get("total"),
                "retryable_pending": stats.get("retryable_pending")}),
            Block(BlockType.TABLE.value, {
                "columns": ["Outcome", "Count"],
                "rows": [[k, v] for k, v in stats.get("by_outcome", {}).items()]})]))
        ir.sections.append(Section(id="issues", title="Issues", blocks=[
            Block(BlockType.TABLE.value, {
                "columns": ["File id", "Outcome", "Attempts", "Terminal", "Detail"],
                "rows": [[i.get("id"), i.get("outcome"), i.get("attempts"),
                          bool(i.get("terminal")), (i.get("detail") or "")[:80]]
                         for i in issues]})], provenance=ProvenanceClass.DERIVED.value))
        matrix = capability_matrix()
        ir.sections.append(Section(id="capabilities", title="Format capabilities", blocks=[
            Block(BlockType.TABLE.value, {
                "columns": ["Format", "Status", "Extensions", "Missing tools"],
                "rows": [[f["format"], f["status"], ", ".join(f["extensions"]),
                          ", ".join(f["missing_tools"])] for f in matrix["formats"]]})],
            provenance=ProvenanceClass.KNOWN.value))
        ir.stats.update({"queued": stats.get("total"), "issues": len(issues)})
