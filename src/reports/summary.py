"""Optional, policy-aware, citation-grounded report summarisation (M018).

* **Optional** — report generation never depends on it. If no provider is
  available the report is still produced; the summary is simply marked
  unavailable.
* **Policy-aware** — it goes through the M012 router. When the remote policy is
  ``never`` the router only offers local providers, so there is **zero external
  traffic**. A blocked remote send is surfaced, never worked around.
* **Source-bounded** — only excerpts the assembler already put in the report are
  sent, each prefixed with its citation. The summariser can never cite a source
  it did not receive: references are re-validated against the provided set and
  anything else is dropped.
* **Labelled** — output is always marked "AI-generated summary" and kept
  distinct from source text.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from .citations import extract_citations
from .models import ReportIR, SummaryResult
from .privacy import mask_text

DEFAULT_MAX_SOURCES = 12
DEFAULT_SOURCE_CHARS = 800
DEFAULT_MAX_CHARS = 6000
SUMMARY_LABEL = "AI-generated summary"

_SYSTEM = (
    "You are a strictly grounded local analyst. Summarise only the numbered "
    "sources given by the user. Every factual sentence must end with one or more "
    "source references copied exactly from the provided list (for example [D1] "
    "or [D2]). Never introduce a reference that was not provided. Never invent "
    "facts, dates or page numbers. If the sources are insufficient, reply with a "
    "single sentence stating that the evidence is insufficient. Do not give "
    "legal or compliance conclusions."
)


def _content(db: Any, file_id: int, limit: int) -> str:
    with db.get_connection() as conn:
        row = conn.execute("SELECT content_text FROM files WHERE id=?",
                           (int(file_id),)).fetchone()
    return (row[0] or "")[:limit] if row else ""


def _provider_available(provider: Any) -> bool:
    try:
        return bool(provider.is_available())
    except Exception:  # noqa: BLE001
        return False


class ReportSummarizer:
    def __init__(self, db: Any, *, provider: Any = None, service: Any = None) -> None:
        self.db = db
        self._provider = provider
        self._service = service

    def _resolve_provider(self) -> Any:
        if self._provider is not None:
            return self._provider
        if self._service is None:
            from ..ai.providers.service import get_ai_service
            self._service = get_ai_service()
        return self._service.llm(content_level="text")

    def available(self) -> dict[str, Any]:
        try:
            provider = self._resolve_provider()
            info = provider.model_info()
            return {"available": _provider_available(provider),
                    "provider": getattr(info, "provider", None) or provider.__class__.__name__,
                    "remote": bool(getattr(info, "remote", False)),
                    "model": getattr(info, "model", None)}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": type(exc).__name__}

    def summarize(self, ir: ReportIR, *, max_sources: int = DEFAULT_MAX_SOURCES,
                  source_chars: int = DEFAULT_SOURCE_CHARS,
                  max_chars: int = DEFAULT_MAX_CHARS) -> SummaryResult:
        mode = ir.definition.privacy_mode
        sendable = [s for s in ir.sources if s.file_id is not None and not s.unavailable]
        if not sendable:
            return SummaryResult(available=False, label=SUMMARY_LABEL,
                                 insufficient_evidence=True,
                                 error="no citable sources in report")
        context_lines: list[str] = []
        provided: list[str] = []
        for src in sendable[:max_sources]:
            fid = src.file_id
            if fid is None:
                continue
            text = mask_text(_content(self.db, int(fid), source_chars), mode).strip()
            if not text:
                continue
            provided.append(src.ref)
            context_lines.append(f"[{src.ref}] {src.label}: {text}")
        if not provided:
            return SummaryResult(available=False, label=SUMMARY_LABEL,
                                 insufficient_evidence=True,
                                 error="no source text available to summarise")

        try:
            provider = self._resolve_provider()
        except Exception as exc:  # noqa: BLE001
            return SummaryResult(available=False, label=SUMMARY_LABEL,
                                 error=f"provider unavailable: {type(exc).__name__}")
        if not _provider_available(provider):
            return SummaryResult(available=False, label=SUMMARY_LABEL,
                                 error="no local/remote LLM provider available")

        task = ir.definition.options.get("summary_task") or (
            "Write a neutral 2-4 sentence overview of what these documents show."
        )
        user = "Sources:\n" + "\n".join(context_lines) + f"\n\nTask: {task}"
        messages = [{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user}]
        try:
            result = provider.chat(messages, options={"max_tokens": 512, "temperature": 0.0})
        except Exception as exc:  # noqa: BLE001 - optional feature, never fatal
            name = type(exc).__name__
            if "RemoteContentBlocked" in name:
                return SummaryResult(available=False, label=SUMMARY_LABEL,
                                     error="remote content blocked by policy; kept local")
            logger.debug(f"M018 summariser provider error: {name}")
            return SummaryResult(available=False, label=SUMMARY_LABEL,
                                 error=f"summary unavailable: {name}")

        text = (getattr(result, "text", "") or "")[:max_chars]
        paragraphs = self._parse(text, provided)
        grounded = any(p["refs"] for p in paragraphs)
        insufficient = (not grounded) or "insufficient" in text.lower()
        return SummaryResult(
            available=True, label=SUMMARY_LABEL,
            provider=getattr(result, "provider", None),
            paragraphs=paragraphs, insufficient_evidence=insufficient and not grounded)

    @staticmethod
    def _parse(text: str, provided: list[str]) -> list[dict[str, Any]]:
        allowed = set(provided)
        paragraphs: list[dict[str, Any]] = []
        for chunk in [c.strip() for c in (text or "").split("\n\n") if c.strip()]:
            found = [r for r in extract_citations(chunk) if r in allowed]
            paragraphs.append({"text": chunk, "refs": found, "grounded": bool(found)})
        return paragraphs
