"""Deterministic, validated source citations for reports (M018).

Reference grammar (stable within a single report):

* ``[D12]``  — document (file id 12 in the report's local numbering)
* ``[D12:p3]`` — document with a *real* page/section location, only when the
  extractor or metadata actually provided it
* ``[E7]``   — entity
* ``[V3]``   — version family
* ``[M4]``   — email message (thread member)
* ``[A2]``   — archive package

Rules enforced here:

* references are assigned in first-seen order (deterministic for a given input);
* every reference resolves to a registered :class:`SourceRef`;
* a citation to a document that no longer exists is marked *unavailable*, never
  silently dropped and never fabricated;
* page/section locations are never invented.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .models import ProvenanceClass, SourceRef

_CITATION_RE = re.compile(r"\[([DEMVA])(\d+)(?::p(\d+))?\]")
_PREFIX_BY_KIND = {
    "document": "D", "entity": "E", "message": "M", "version_family": "V",
    "archive": "A",
}


class CitationError(ValueError):
    """Raised when a citation cannot be resolved (fail-closed)."""


class CitationRegistry:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, Any], str] = {}
        self._sources: dict[str, SourceRef] = {}
        self._counters: dict[str, int] = {}

    # -- assignment --------------------------------------------------------
    def _next_ref(self, kind: str) -> str:
        prefix = _PREFIX_BY_KIND.get(kind, "D")
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}{n}"

    def _register(self, kind: str, key: Any, source: SourceRef) -> SourceRef:
        existing = self._by_key.get((kind, key))
        if existing is not None:
            return self._sources[existing]
        ref = self._next_ref(kind)
        source.ref = ref
        source.kind = kind
        self._by_key[(kind, key)] = ref
        self._sources[ref] = source
        return source

    def document(self, file_id: int, *, label: str = "", path: str | None = None,
                 date: str | None = None, date_source: str | None = None,
                 date_class: str = ProvenanceClass.UNAVAILABLE.value,
                 extraction_state: str | None = None, score: float | None = None,
                 location: str | None = None,
                 provenance: str = ProvenanceClass.KNOWN.value,
                 relations: list[dict[str, Any]] | None = None,
                 unavailable: bool = False, note: str | None = None) -> SourceRef:
        return self._register("document", int(file_id), SourceRef(
            ref="", kind="document", file_id=int(file_id), label=label or f"document {file_id}",
            path=path, date=date, date_source=date_source, date_class=date_class,
            extraction_state=extraction_state, score=score, location=location,
            provenance=provenance, relations=list(relations or []),
            unavailable=unavailable, note=note))

    def entity(self, value: str, *, label: str | None = None,
               provenance: str = ProvenanceClass.KNOWN.value) -> SourceRef:
        return self._register("entity", value, SourceRef(
            ref="", kind="entity", label=label or value, provenance=provenance))

    def version_family(self, family_key: str, *, label: str = "",
                       provenance: str = ProvenanceClass.DERIVED.value) -> SourceRef:
        return self._register("version_family", family_key, SourceRef(
            ref="", kind="version_family", label=label or f"version family {family_key}",
            provenance=provenance))

    def message(self, file_id: int, **kwargs: Any) -> SourceRef:
        # A message keeps its document ref (D..) so the appendix stays one list.
        return self.document(file_id, **kwargs)

    def archive(self, file_id: int, **kwargs: Any) -> SourceRef:
        return self.document(file_id, **kwargs)

    # -- lookup / validation ----------------------------------------------
    def sources(self) -> list[SourceRef]:
        return list(self._sources.values())

    def resolve(self, ref: str) -> SourceRef | None:
        return self._sources.get(ref)

    def ref_for_document(self, file_id: int) -> str | None:
        return self._by_key.get(("document", int(file_id)))

    def validate(self, text: str) -> list[str]:
        """Return dangling references found in ``text`` (empty == valid)."""
        dangling: list[str] = []
        for match in _CITATION_RE.finditer(text or ""):
            ref = match.group(1) + match.group(2)
            if ref not in self._sources:
                dangling.append(ref)
        return dangling

    def validate_refs(self, refs: Iterable[str]) -> list[str]:
        return [r for r in refs if r not in self._sources]

    def appendix(self) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self._sources.values()]


def extract_citations(text: str) -> list[str]:
    """Return the distinct citation tokens (without page suffix) in order."""
    seen: list[str] = []
    for match in _CITATION_RE.finditer(text or ""):
        ref = match.group(1) + match.group(2)
        if ref not in seen:
            seen.append(ref)
    return seen


def citation_with_location(ref: str, location: str | None) -> str:
    """Return ``[D1]`` or ``[D1:p3]`` only when a location truly exists."""
    if not location:
        return f"[{ref}]"
    digit = str(location).strip().lstrip("pP")
    if digit.isdigit():
        return f"[{ref}:p{digit}]"
    return f"[{ref}]"
