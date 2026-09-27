"""Canonical report / dossier intermediate representation (M018).

The report layer turns indexed intelligence into deliverables. It never copies
documents into a parallel store: a report is a *definition* plus a *rendered
artifact*, both derived from the canonical SQLite database and the existing
services (search, dedup, graph, intel, ingest).

This module is deliberately renderer-agnostic. The same :class:`ReportIR` feeds
the HTML exporter, the PDF exporter and the JSON representation, so content is
never coupled to a single output format.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Bumped whenever the IR/assembly semantics change; recorded in manifests.
GENERATOR_VERSION = "m018.1"
IR_SCHEMA = "report-ir/v1"


class ReportKind(str, Enum):
    SEARCH = "SEARCH"
    DOSSIER = "DOSSIER"
    TIMELINE = "TIMELINE"
    DUPLICATES = "DUPLICATES"
    ENTITY_CATEGORY = "ENTITY_CATEGORY"
    PII_SUMMARY = "PII_SUMMARY"
    INGESTION = "INGESTION"
    PROJECT = "PROJECT"


class ReportFormat(str, Enum):
    HTML = "HTML"
    PDF = "PDF"
    JSON = "JSON"


class PrivacyMode(str, Enum):
    """Export privacy modes. A mode is never silently downgraded."""

    FULL_LOCAL = "FULL_LOCAL"
    MASK_PII = "MASK_PII"
    OMIT_HIGH_SENSITIVITY = "OMIT_HIGH_SENSITIVITY"
    PATH_REDACTED = "PATH_REDACTED"
    METADATA_ONLY = "METADATA_ONLY"


class ProvenanceClass(str, Enum):
    """How a factual field came to be. Never present unknown data as known."""

    KNOWN = "KNOWN"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"
    UNAVAILABLE = "UNAVAILABLE"


class DossierMode(str, Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    DOCUMENT_CARD = "document_card"
    CITATION = "citation"
    IMAGE = "image"
    TIMELINE = "timeline"
    GRAPH_SUMMARY = "graph_summary"
    WARNING = "warning"
    METADATA = "metadata"
    SOURCE_APPENDIX = "source_appendix"
    SUMMARY = "summary"


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


@dataclass
class SourceRef:
    """A provenance-bearing reference to a factual item in a report."""

    ref: str
    kind: str = "document"
    file_id: int | None = None
    label: str = ""
    path: str | None = None
    date: str | None = None
    date_source: str | None = None
    date_class: str = ProvenanceClass.UNAVAILABLE.value
    extraction_state: str | None = None
    relations: list[dict[str, Any]] = field(default_factory=list)
    score: float | None = None
    location: str | None = None
    provenance: str = ProvenanceClass.KNOWN.value
    omitted: bool = False
    unavailable: bool = False
    note: str | None = None

    @property
    def citation(self) -> str:
        return f"[{self.ref}]"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref, "kind": self.kind, "file_id": self.file_id,
            "label": self.label, "path": self.path, "date": self.date,
            "date_source": self.date_source, "date_class": self.date_class,
            "extraction_state": self.extraction_state, "relations": self.relations,
            "score": self.score, "location": self.location, "provenance": self.provenance,
            "omitted": self.omitted, "unavailable": self.unavailable, "note": self.note,
        }


@dataclass
class Block:
    type: str  # noqa: A003 - "type" is the IR contract name
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


@dataclass
class Section:
    id: str  # noqa: A003 - "id" is the IR contract name
    title: str
    blocks: list[Block] = field(default_factory=list)
    provenance: str = ProvenanceClass.KNOWN.value

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "provenance": self.provenance,
                "blocks": [b.as_dict() for b in self.blocks]}


@dataclass
class ReportDefinition:
    """A reproducible report recipe. Regenerable while sources still exist."""

    report_id: str
    kind: str
    title: str
    description: str = ""
    created_at: str = field(default_factory=_now_iso)
    query: dict[str, Any] = field(default_factory=dict)
    document_ids: list[int] = field(default_factory=list)
    privacy_mode: str = PrivacyMode.FULL_LOCAL.value
    options: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id, "kind": self.kind, "title": self.title,
            "description": self.description, "created_at": self.created_at,
            "query": self.query, "document_ids": list(self.document_ids),
            "privacy_mode": self.privacy_mode, "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportDefinition:
        return cls(
            report_id=str(data.get("report_id") or ""),
            kind=str(data.get("kind") or ReportKind.SEARCH.value),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            created_at=str(data.get("created_at") or _now_iso()),
            query=dict(data.get("query") or {}),
            document_ids=[int(i) for i in (data.get("document_ids") or [])],
            privacy_mode=str(data.get("privacy_mode") or PrivacyMode.FULL_LOCAL.value),
            options=dict(data.get("options") or {}),
        )


@dataclass
class SummaryResult:
    """Optional AI summary. Always labelled and always citation-grounded."""

    available: bool
    label: str = "AI-generated summary"
    provider: str | None = None
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    insufficient_evidence: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available, "label": self.label, "provider": self.provider,
            "paragraphs": self.paragraphs,
            "insufficient_evidence": self.insufficient_evidence, "error": self.error,
        }


@dataclass
class ReportIR:
    """Structured, renderer-agnostic report content."""

    definition: ReportDefinition
    generated_at: str = field(default_factory=_now_iso)
    generator_version: str = GENERATOR_VERSION
    schema: str = IR_SCHEMA
    sections: list[Section] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    omitted: list[dict[str, Any]] = field(default_factory=list)
    summary: SummaryResult | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    # -- serialisation -----------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generator_version": self.generator_version,
            "generated_at": self.generated_at,
            "definition": self.definition.as_dict(),
            "stats": self.stats,
            "sections": [s.as_dict() for s in self.sections],
            "sources": [s.as_dict() for s in self.sources],
            "warnings": list(self.warnings),
            "omitted": list(self.omitted),
            "summary": self.summary.as_dict() if self.summary else None,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent, sort_keys=False)

    def source_by_ref(self, ref: str) -> SourceRef | None:
        for src in self.sources:
            if src.ref == ref:
                return src
        return None

    def logical_fingerprint(self) -> str:
        """Deterministic hash of the *logical* content (not renderer bytes).

        Excludes volatile fields (generation timestamp, artifact paths) so two
        identical definitions over unchanged inputs produce the same value.
        """
        import hashlib
        payload = {
            "schema": self.schema,
            "generator_version": self.generator_version,
            "definition": self.definition.as_dict(),
            "sections": [s.as_dict() for s in self.sections],
            "sources": [s.as_dict() for s in self.sources],
            "warnings": list(self.warnings),
            "omitted": list(self.omitted),
            "summary": self.summary.as_dict() if self.summary else None,
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass
class ReportArtifact:
    report_id: str
    format: str  # noqa: A003 - "format" is the artifact contract name
    path: str
    checksum: str
    size_bytes: int
    generated_at: str
    generator_version: str = GENERATOR_VERSION
    privacy_mode: str = PrivacyMode.FULL_LOCAL.value
    provider: str | None = None
    warnings: list[str] = field(default_factory=list)
    logical_fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id, "format": self.format, "path": self.path,
            "checksum": self.checksum, "size_bytes": self.size_bytes,
            "generated_at": self.generated_at, "generator_version": self.generator_version,
            "privacy_mode": self.privacy_mode, "provider": self.provider,
            "warnings": list(self.warnings), "logical_fingerprint": self.logical_fingerprint,
        }


@dataclass
class ReportManifest:
    """Reproducibility manifest written next to every artifact."""

    report_id: str
    title: str
    kind: str
    generated_at: str
    generator_version: str
    privacy_mode: str
    logical_fingerprint: str
    source_document_ids: list[int] = field(default_factory=list)
    source_hashes: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    omitted: list[dict[str, Any]] = field(default_factory=list)
    exporter: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id, "title": self.title, "kind": self.kind,
            "generated_at": self.generated_at, "generator_version": self.generator_version,
            "privacy_mode": self.privacy_mode,
            "logical_fingerprint": self.logical_fingerprint,
            "source_document_ids": list(self.source_document_ids),
            "source_hashes": list(self.source_hashes),
            "artifacts": list(self.artifacts),
            "warnings": list(self.warnings), "omitted": list(self.omitted),
            "exporter": self.exporter,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=indent)
