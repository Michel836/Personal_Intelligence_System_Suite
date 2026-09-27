"""M015 document-understanding + local-privacy intelligence layer.

Adds language detection, named entities, configurable categorisation, PII
classification, privacy-aware filters, a non-destructive redaction preview and a
local audit trail on top of the canonical SQLite/extraction/semantic stack.

All processing is local. No account/RBAC/telemetry and no mandatory external
API. PII findings are persisted masked + fingerprinted; raw values never reach
logs or committed artifacts.
"""
from __future__ import annotations

from .audit import ACTIONS, AuditTrail
from .categories import CategoryEngine
from .entities import RELIABLE_TYPES, extract_entities
from .language import LANGUAGE_NAMES, detect_language
from .pii import SEVERITY, detect_pii, is_sensitive
from .pipeline import IntelPipeline
from .privacy import remote_policy_state, remote_warning
from .redact import redact_text, redacted_preview
from .relationships import (
    documents_by_category,
    documents_by_language,
    documents_sharing_entity,
    entity_frequency,
)
from .search import filter_options, search_with_intelligence
from .store import IntelStore

__all__ = [
    "IntelStore", "IntelPipeline", "AuditTrail", "ACTIONS", "CategoryEngine",
    "detect_language", "LANGUAGE_NAMES", "extract_entities", "RELIABLE_TYPES",
    "detect_pii", "SEVERITY", "is_sensitive", "redact_text", "redacted_preview",
    "filter_options", "search_with_intelligence", "entity_frequency",
    "documents_sharing_entity", "documents_by_language", "documents_by_category",
    "remote_policy_state", "remote_warning",
]
