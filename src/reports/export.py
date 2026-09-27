"""Export orchestration: build → render → manifest → history (M018).

Safety properties:

* the export directory is explicit and configurable (``PIS_EXPORT_DIR``,
  default ``~/.pis-exports``), never inside a scanned source tree by default;
* every path is joined safely and must resolve inside the export directory
  (no traversal);
* files are written to a temp sibling and atomically moved into place;
* names are collision-resistant (report id + timestamp + random suffix);
* an existing artifact is never overwritten silently — the caller must pass
  ``overwrite=True``;
* a manifest records what was exported, the privacy mode, source ids/hashes and
  the logical fingerprint, so the same definition over unchanged inputs is
  reproducible (logically; byte-identical PDF is not claimed).
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .builders import ReportBuilder
from .html_export import render_html
from .models import (
    GENERATOR_VERSION,
    Block,
    BlockType,
    PrivacyMode,
    ReportArtifact,
    ReportDefinition,
    ReportFormat,
    ReportIR,
    ReportManifest,
    Section,
)
from .pdf_export import PdfResult, available_providers, render_pdf
from .privacy import includes_content
from .provenance import content_hash, file_row
from .store import ReportStore

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def default_export_dir() -> Path:
    env = os.environ.get("PIS_EXPORT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".pis-exports"


def safe_component(value: str, *, max_len: int = 64) -> str:
    cleaned = _SAFE.sub("-", (value or "").strip()).strip("-._")
    return (cleaned or "report")[:max_len]


def new_report_id(kind: str) -> str:
    return f"rpt_{safe_component(kind, max_len=12).lower()}_{uuid.uuid4().hex[:10]}"


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _stamp(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)[:14] or "0"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass
class ExportResult:
    definition: ReportDefinition
    ir: ReportIR
    manifest: ReportManifest
    artifacts: list[ReportArtifact] = field(default_factory=list)
    pdf: PdfResult | None = None
    manifest_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def paths(self) -> list[str]:
        return [a.path for a in self.artifacts]


class ExportService:
    def __init__(self, db: Any, *, store: ReportStore | None = None,
                 builder: ReportBuilder | None = None, out_dir: Path | str | None = None,
                 pdf_provider: str | None = None, summarizer: Any = None) -> None:
        self.db = db
        self.store = store or ReportStore(db)
        self.builder = builder or ReportBuilder(db)
        self.out_dir = Path(out_dir) if out_dir else default_export_dir()
        self.pdf_provider = pdf_provider
        self.summarizer = summarizer

    # -- path safety -------------------------------------------------------
    def _ensure_dir(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir.resolve()

    def _safe_path(self, filename: str) -> Path:
        root = self._ensure_dir()
        candidate = (root / filename).resolve()
        if root != candidate.parent and root not in candidate.parents:
            raise ValueError("refusing to write outside the export directory")
        return candidate

    def _artifact_name(self, definition: ReportDefinition, ext: str, fingerprint: str) -> str:
        # A random token is always included so concurrent generations can never
        # collide on the same path (collision-resistant by construction).
        return (f"{safe_component(definition.report_id, max_len=40)}-"
                f"{_stamp(_now_iso())}-{fingerprint[:8]}-{uuid.uuid4().hex[:6]}.{ext}")

    # -- definition --------------------------------------------------------
    def create_definition(self, kind: str, title: str, *, description: str = "",
                          privacy_mode: str = PrivacyMode.FULL_LOCAL.value,
                          query: dict[str, Any] | None = None,
                          document_ids: list[int] | None = None,
                          options: dict[str, Any] | None = None) -> ReportDefinition:
        return ReportDefinition(
            report_id=new_report_id(kind), kind=kind, title=title, description=description,
            privacy_mode=privacy_mode, query=query or {}, document_ids=document_ids or [],
            options=options or {})

    def save_definition(self, definition: ReportDefinition) -> None:
        self.store.save_definition(definition)

    def get_definition(self, report_id: str) -> ReportDefinition | None:
        return self.store.get_definition(report_id)

    # -- generation --------------------------------------------------------
    def generate(self, definition: ReportDefinition, *,
                 formats: tuple[str, ...] = (ReportFormat.HTML.value, ReportFormat.PDF.value,
                                             ReportFormat.JSON.value),
                 summarize: bool = False, overwrite: bool = False) -> ExportResult:
        self.store.save_definition(definition)
        ir = self.builder.build(definition)
        if summarize and includes_content(definition.privacy_mode):
            self._attach_summary(ir)
        elif summarize:
            ir.warnings.append("summary skipped: privacy mode excludes content")
        return self._render(ir, formats=formats, overwrite=overwrite)

    def regenerate(self, report_id: str, *,
                   formats: tuple[str, ...] = (ReportFormat.HTML.value, ReportFormat.PDF.value,
                                               ReportFormat.JSON.value),
                   summarize: bool = False, overwrite: bool = False) -> ExportResult | None:
        definition = self.store.get_definition(report_id)
        if definition is None:
            return None
        return self.generate(definition, formats=formats, summarize=summarize,
                             overwrite=overwrite)

    def _attach_summary(self, ir: ReportIR) -> None:
        if self.summarizer is None:
            from .summary import ReportSummarizer
            self.summarizer = ReportSummarizer(self.db)
        result = self.summarizer.summarize(ir)
        ir.summary = result
        if result.available and result.paragraphs:
            section = Section(
                id="ai-summary", title="AI-generated summary",
                blocks=[Block(BlockType.SUMMARY.value, {
                    "label": result.label, "paragraphs": result.paragraphs,
                    "insufficient_evidence": result.insufficient_evidence})],
                provenance="DERIVED")
            ir.sections.insert(0, section)
        elif result.error:
            ir.warnings.append(f"summary unavailable: {result.error}")

    # -- rendering ---------------------------------------------------------
    def _render(self, ir: ReportIR, *, formats: tuple[str, ...],
                overwrite: bool) -> ExportResult:
        definition = ir.definition
        fingerprint = ir.logical_fingerprint()
        result = ExportResult(definition=definition, ir=ir,
                              manifest=self._manifest(ir, fingerprint))
        if not overwrite:
            for existing in self.store.artifacts_for(definition.report_id):
                if existing.get("logical_fingerprint") == fingerprint and existing.get("exists"):
                    result.warnings.append(
                        "an identical artifact already exists; reusing is not automatic "
                        "(pass overwrite=True to regenerate)")
                    break
        rendered_html: str | None = None
        if ReportFormat.HTML.value in formats:
            rendered_html = render_html(ir)
            artifact = self._write(definition, rendered_html.encode("utf-8"),
                                   ReportFormat.HTML.value, "html", fingerprint)
            result.artifacts.append(artifact)
        if ReportFormat.PDF.value in formats:
            html_text = rendered_html if rendered_html is not None else render_html(ir)
            pdf_artifact, pdf_result = self._write_pdf(definition, html_text, fingerprint)
            if pdf_artifact is not None:
                result.artifacts.append(pdf_artifact)
            result.pdf = pdf_result
            if pdf_result is not None and not pdf_result.ok:
                result.warnings.append(f"PDF not generated: {pdf_result.error}")
                ir.warnings.append(f"PDF not generated: {pdf_result.error}")
        if ReportFormat.JSON.value in formats:
            artifact = self._write(definition, ir.to_json().encode("utf-8"),
                                   ReportFormat.JSON.value, "json", fingerprint)
            result.artifacts.append(artifact)

        result.manifest.artifacts = [a.as_dict() for a in result.artifacts]
        result.manifest.warnings = list(ir.warnings)
        result.manifest.omitted = list(ir.omitted)
        result.manifest.exporter = result.pdf.provider if result.pdf else None
        manifest_bytes = result.manifest.to_json().encode("utf-8")
        manifest_path = self._safe_path(
            self._artifact_name(definition, "manifest.json", fingerprint))
        _atomic_write(manifest_path, manifest_bytes)
        result.manifest_path = str(manifest_path)
        result.manifest.artifacts.append({
            "format": "MANIFEST", "path": str(manifest_path),
            "checksum": _sha256_bytes(manifest_bytes), "size_bytes": len(manifest_bytes)})
        for artifact in result.artifacts:
            self.store.record_artifact(artifact)
        return result

    def _write(self, definition: ReportDefinition, data: bytes, fmt: str,
               ext: str, fingerprint: str) -> ReportArtifact:
        path = self._safe_path(self._artifact_name(definition, ext, fingerprint))
        _atomic_write(path, data)
        return ReportArtifact(
            report_id=definition.report_id, format=fmt, path=str(path),
            checksum=_sha256_bytes(data), size_bytes=len(data), generated_at=_now_iso(),
            generator_version=GENERATOR_VERSION, privacy_mode=definition.privacy_mode,
            logical_fingerprint=fingerprint)

    def _write_pdf(self, definition: ReportDefinition, html_text: str,
                   fingerprint: str) -> tuple[ReportArtifact | None, PdfResult | None]:
        if not available_providers().get(self.pdf_provider or "libreoffice", {}).get("available") \
                and not any(v["available"] for v in available_providers().values()):
            return None, PdfResult(False, error="no local PDF provider available")
        path = self._safe_path(self._artifact_name(definition, "pdf", fingerprint))
        pdf_result = render_pdf(html_text, path, provider=self.pdf_provider)
        if not pdf_result.ok:
            return None, pdf_result
        data = path.read_bytes()
        artifact = ReportArtifact(
            report_id=definition.report_id, format=ReportFormat.PDF.value, path=str(path),
            checksum=_sha256_bytes(data), size_bytes=len(data), generated_at=_now_iso(),
            generator_version=GENERATOR_VERSION, privacy_mode=definition.privacy_mode,
            provider=pdf_result.provider, logical_fingerprint=fingerprint)
        return artifact, pdf_result

    def _manifest(self, ir: ReportIR, fingerprint: str) -> ReportManifest:
        hashes: list[dict[str, Any]] = []
        for src in ir.sources:
            if src.file_id is None:
                continue
            h = content_hash(self.db, int(src.file_id))
            row = file_row(self.db, int(src.file_id)) or {}
            hashes.append({
                "file_id": int(src.file_id),
                "ref": src.ref,
                "content_hash": (h or {}).get("digest"),
                "size_bytes": row.get("size_bytes"),
                "modified_at": row.get("modified_at"),
                "available": not src.unavailable,
            })
        return ReportManifest(
            report_id=ir.definition.report_id, title=ir.definition.title,
            kind=ir.definition.kind, generated_at=ir.generated_at,
            generator_version=ir.generator_version,
            privacy_mode=ir.definition.privacy_mode, logical_fingerprint=fingerprint,
            source_document_ids=[s.file_id for s in ir.sources if s.file_id is not None],
            source_hashes=hashes, warnings=list(ir.warnings), omitted=list(ir.omitted))
