"""M018 output & synthesis layer: reports, dossiers, exports, reconstruction.

Local-only. A report is a reproducible *definition* plus a rendered *artifact*
derived from the canonical database; no parallel document store is created, no
source file is modified, and nothing is sent remotely unless the operator has
explicitly allowed it through the M012 policy.
"""
from __future__ import annotations

from .builders import ReportBuilder
from .citations import CitationError, CitationRegistry, extract_citations
from .dossiers import DossierService, run_query
from .export import ExportResult, ExportService, default_export_dir, new_report_id
from .html_export import render_html
from .models import (
    GENERATOR_VERSION,
    Block,
    BlockType,
    DossierMode,
    PrivacyMode,
    ProvenanceClass,
    ReportArtifact,
    ReportDefinition,
    ReportFormat,
    ReportIR,
    ReportKind,
    ReportManifest,
    Section,
    SourceRef,
    SummaryResult,
)
from .pdf_export import available_providers, render_pdf
from .privacy import PRIVACY_MODES, all_mode_descriptions, describe_mode
from .provenance import build_source, content_hash, file_row, resolve_date
from .reconstruction import EvidencePack
from .store import ReportStore
from .summary import ReportSummarizer

__all__ = [
    "ReportBuilder", "ReportStore", "ExportService", "ExportResult",
    "DossierService", "run_query", "default_export_dir", "new_report_id",
    "CitationRegistry", "CitationError", "extract_citations",
    "render_html", "render_pdf", "available_providers",
    "ReportSummarizer", "EvidencePack",
    "build_source", "file_row", "content_hash", "resolve_date",
    "PRIVACY_MODES", "all_mode_descriptions", "describe_mode",
    "ReportDefinition", "ReportIR", "ReportManifest", "ReportArtifact",
    "ReportKind", "ReportFormat", "PrivacyMode", "ProvenanceClass", "DossierMode",
    "Block", "BlockType", "Section", "SourceRef", "SummaryResult",
    "GENERATOR_VERSION",
]
