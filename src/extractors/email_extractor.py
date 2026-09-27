"""Canonical email extraction: EML / MHT / MSG (M017).

Local-only, bounded and tolerant of malformed MIME. Uses the stdlib email
package for EML/MHT and a bounded CFB reader for Outlook MSG. Never executes
attachments, never writes to source files, and logs only aggregate counts (never
addresses or content).
"""
from __future__ import annotations

import time
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from loguru import logger

from .base import BaseExtractor, ExtractionResult

MAX_MESSAGE_BYTES = 50 * 1024 * 1024
MAX_BODY_CHARS = 2_000_000
MAX_ATTACHMENTS = 200
MAX_NESTED_DEPTH = 2


class _TextFromHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, _attrs: Any) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextFromHTML()
    try:
        parser.feed(html)
    except Exception:
        return html
    text = "".join(parser.parts)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _decode_msg_stream(raw: bytes, unicode_stream: bool) -> str:
    if unicode_stream:
        return raw.decode("utf-16-le", "ignore").rstrip("\x00")
    return raw.decode("latin-1", "ignore").rstrip("\x00")


def _msg_property(streams: dict[str, bytes], code: str) -> str | None:
    for suffix, is_unicode in (("001F", True), ("001E", False)):
        key = f"__substg1.0_{code}{suffix}"
        if key in streams:
            return _decode_msg_stream(streams[key], is_unicode)
    return None


def _extract_msg(path: Path, start_time: float) -> ExtractionResult:
    from ..ingest.cfb import CfbError, read_cfb_streams

    try:
        streams = read_cfb_streams(path)
    except CfbError as exc:
        return ExtractionResult(success=False, error=f"MSG malformed: {exc}",
                                extraction_time=time.time() - start_time)
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(success=False, error=f"MSG error: {exc}",
                                extraction_time=time.time() - start_time)
    if not streams:
        return ExtractionResult(success=False, error="MSG malformed: no property streams",
                                extraction_time=time.time() - start_time)
    subject = _msg_property(streams, "0037")
    body = _msg_property(streams, "1000")
    sender_name = _msg_property(streams, "0C1A")
    sender_email = _msg_property(streams, "0C1F")
    to_display = _msg_property(streams, "0E04")
    date = _msg_property(streams, "0039")
    parts = [p for p in (subject, sender_name, sender_email, to_display, date) if p]
    content = "\n".join(parts)
    if body:
        content = f"{content}\n\n{body}" if content else body
    content = content[:MAX_BODY_CHARS].strip()
    metadata: dict[str, Any] = {"format": "MSG", "subject": subject, "sender_name": sender_name,
                "sender_email": sender_email, "to": to_display, "date": date,
                "streams": len(streams), "attachments": []}
    if not content:
        return ExtractionResult(success=True, content="", metadata=metadata,
                                extraction_time=time.time() - start_time)
    return ExtractionResult(success=True, content=content, metadata=metadata,
                            extraction_time=time.time() - start_time)


def _extract_mime(data: bytes, start_time: float, fmt: str) -> ExtractionResult:
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:  # noqa: BLE001 - tolerance for malformed MIME
        return ExtractionResult(success=False, error=f"malformed MIME: {exc}",
                                extraction_time=time.time() - start_time)
    subject = msg.get("Subject")
    from_ = msg.get("From")
    to = msg.get("To")
    cc = msg.get("Cc")
    date = msg.get("Date")
    message_id = msg.get("Message-ID")
    in_reply_to = msg.get("In-Reply-To")
    references = msg.get("References")
    text_parts: list[tuple[int, str]] = []
    html_parts: list[tuple[int, str]] = []
    attachments: list[dict[str, Any]] = []
    nested = 0

    def walk(part: Any, depth: int) -> None:
        nonlocal nested
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment" or part.get_filename():
            if len(attachments) < MAX_ATTACHMENTS:
                try:
                    payload = part.get_payload(decode=True) or b""
                except Exception:
                    payload = b""
                attachments.append({"filename": part.get_filename(), "content_type": ctype,
                                    "size": len(payload)})
            return
        if ctype == "message/rfc822" and depth < MAX_NESTED_DEPTH:
            nested += 1
            for sub in part.get_payload():
                if hasattr(sub, "walk"):
                    walk(sub, depth + 1)
            return
        if part.is_multipart():
            for sub in part.get_payload():
                if hasattr(sub, "walk"):
                    walk(sub, depth)
            return
        try:
            payload = part.get_content()
        except Exception:
            try:
                payload = part.get_payload(decode=True).decode("utf-8", "replace")
            except Exception:
                payload = ""
        if ctype == "text/plain":
            text_parts.append((depth, payload))
        elif ctype == "text/html":
            html_parts.append((depth, payload))

    # Single traversal from the root: ``msg.walk()`` already descends into
    # every subpart, so iterating it *and* recursing here double-counted
    # attachments and reprocessed nested messages. Bodies are kept per depth so
    # a nested ``message/rfc822`` body is not silently dropped.
    walk(msg, 0)

    def _best(parts: list[tuple[int, str]], depth: int) -> str:
        for d, text in parts:
            if d == depth and (text or "").strip():
                return text
        return ""

    body_chunks: list[str] = []
    for depth in sorted({d for d, _ in (*text_parts, *html_parts)}):
        plain = _best(text_parts, depth)
        chunk = plain if plain.strip() else (
            html_to_text(_best(html_parts, depth)) if _best(html_parts, depth) else "")
        if chunk.strip():
            body_chunks.append(chunk)
    body = "\n\n".join(body_chunks)
    header_lines = []
    for label, value in (("Subject", subject), ("From", from_), ("To", to), ("Cc", cc),
                         ("Date", date), ("Message-ID", message_id),
                         ("In-Reply-To", in_reply_to), ("References", references)):
        if value:
            header_lines.append(f"{label}: {value}")
    content = "\n".join(header_lines)
    if body:
        content = f"{content}\n\n{body}" if content else body
    content = content[:MAX_BODY_CHARS].strip()
    metadata = {"format": fmt, "subject": subject, "from": from_, "to": to, "cc": cc,
                "date": date, "message_id": message_id, "in_reply_to": in_reply_to,
                "references": references, "attachments": attachments, "nested": nested}
    if not content:
        return ExtractionResult(success=True, content="", metadata=metadata,
                                extraction_time=time.time() - start_time)
    return ExtractionResult(success=True, content=content, metadata=metadata,
                            extraction_time=time.time() - start_time)


class EmailExtractor(BaseExtractor):
    """Extract EML / MHT / MHTML / MSG messages (metadata + body text)."""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.supported_extensions = {".eml", ".mht", ".mhtml", ".msg"}

    def can_extract(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions and file_path.is_file()

    def extract_content(self, file_path: Path) -> ExtractionResult:
        start = time.time()
        ext = file_path.suffix.lower()
        try:
            if file_path.stat().st_size > MAX_MESSAGE_BYTES:
                return ExtractionResult(success=False, error="message exceeds size limit",
                                        extraction_time=time.time() - start)
            if ext == ".msg":
                return _extract_msg(file_path, start)
            data = file_path.read_bytes()
            return _extract_mime(data, start, "MHT" if ext in {".mht", ".mhtml"} else "EML")
        except Exception as exc:  # noqa: BLE001 - failure isolation
            logger.debug(f"email extraction failed for {file_path.name}: {type(exc).__name__}")
            return ExtractionResult(success=False, error=f"email error: {exc}",
                                    extraction_time=time.time() - start)
