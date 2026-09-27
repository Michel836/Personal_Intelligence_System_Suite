"""Deterministic, public-safe release acceptance corpus (M021).

Builds a compact corpus covering the formats, lifecycle cases, duplicates,
versions, multilingual text, synthetic PII, dates, malformed/unsupported files
and an archive. Nothing here is private and every byte is generated locally.

The builder is import-safe (no pytest dependency) so both the release tests and
``scripts/release/make_acceptance_corpus.py`` can call it.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Deterministic modification times (UTC) used for timeline tests.
MTIMES = {
    "alpha": datetime(2023, 1, 15, 9, 0, tzinfo=UTC),
    "beta": datetime(2023, 6, 1, 10, 0, tzinfo=UTC),
    "gamma": datetime(2024, 3, 20, 11, 0, tzinfo=UTC),
    "delta": datetime(2024, 11, 5, 12, 0, tzinfo=UTC),
}

#: Synthetic (fabricated) identifiers with valid checksums for detector tests.
SYNTHETIC_EMAIL = "release.fixture@example.test"
SYNTHETIC_IBAN = "FR7630006000011234567890189"  # public SEPA example, mod-97 valid
SYNTHETIC_CARD = "4111111111111111"  # standard Luhn-valid test number
SYNTHETIC_PHONE = "+33 6 12 34 56 78"


@dataclass
class CorpusEntry:
    relpath: str
    kind: str
    sha256: str
    size: int
    expect: str = "extractable"


@dataclass
class AcceptanceCorpus:
    root: Path
    entries: list[CorpusEntry] = field(default_factory=list)

    @property
    def manifest(self) -> dict[str, Any]:
        return {"root_name": self.root.name, "count": len(self.entries),
                "entries": [{"relpath": e.relpath, "kind": e.kind, "sha256": e.sha256,
                             "size": e.size, "expect": e.expect} for e in self.entries]}

    def hashes(self) -> dict[str, str]:
        return {e.relpath: e.sha256 for e in self.entries}

    def by_kind(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for entry in self.entries:
            out.setdefault(entry.kind, []).append(entry.relpath)
        return out

    def path(self, relpath: str) -> Path:
        return self.root / relpath


def _write(entry_root: Path, entries: list[CorpusEntry], relpath: str, data: bytes,
           *, kind: str, expect: str = "extractable") -> Path:
    path = entry_root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    entries.append(CorpusEntry(relpath=relpath, kind=kind,
                               sha256=hashlib.sha256(data).hexdigest(),
                               size=len(data), expect=expect))
    return path


def _minimal_pdf(text: str) -> bytes:
    """Build a tiny, valid single-page PDF with a real text stream."""
    content = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n"
            f"{xref}\n%%EOF\n").encode()
    return bytes(out)


def _scanned_pdf() -> bytes:
    """Image-only PDF (no text layer) for OCR-candidate classification."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return b"%PDF-1.4\n% image-only placeholder\n%%EOF\n"
    import io
    image = Image.new("RGB", (200, 80), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


def _docx(text: str) -> bytes:
    import io

    from docx import Document
    document = Document()
    document.add_heading("Release Acceptance", level=1)
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _xlsx() -> bytes:
    import io

    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Release"
    sheet.append(["theme", "value"])
    sheet.append(["finance", "invoice bank revenue"])
    sheet.append(["health", "patient clinical research"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _odt(text: str) -> bytes:
    import io

    from odf.opendocument import OpenDocumentText
    from odf.text import P
    document = OpenDocumentText()
    document.text.addElement(P(text=text))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _epub(text: str) -> bytes:
    """Minimal valid EPUB built with the stdlib zip writer."""
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" '
                    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                    'media-type="application/oebps-package+xml"/></rootfiles></container>')
        zf.writestr("OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                    'version="2.0" unique-identifier="id"><metadata '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    '<dc:title>Release Book</dc:title><dc:identifier id="id">rel-1</dc:identifier>'
                    '</metadata><manifest><item id="c1" href="chapter1.xhtml" '
                    'media-type="application/xhtml+xml"/></manifest>'
                    '<spine><itemref idref="c1"/></spine></package>')
        zf.writestr("OEBPS/chapter1.xhtml",
                    '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Release</h1>'
                    f'<p>{text}</p></body></html>')
    return buffer.getvalue()


def _archive() -> bytes:
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("members/inside_a.txt", "archive member alpha finance invoice bank")
        zf.writestr("members/inside_b.txt", "archive member beta compiler python network")
        zf.writestr("members/notes.md", "# Archive notes\narchive member gamma legal contract")
    return buffer.getvalue()


def _msg_stub() -> bytes:
    """A bounded CFB-shaped stub so the native MSG path is exercised safely."""
    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    return header + b"\x00" * 512 + b"__release_stub__"


def _set_mtime(path: Path, moment: datetime) -> None:
    stamp = moment.timestamp()
    os.utime(path, (stamp, stamp))


def build_acceptance_corpus(root: Path) -> AcceptanceCorpus:
    """Create the corpus under ``root`` and return its manifest+hashes."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    entries: list[CorpusEntry] = []

    # -- plain text family -------------------------------------------------
    _write(root, entries, "docs/alpha_finance.txt",
           (f"Alpha quarterly finance report. Invoice bank payment accounting revenue tax. "
            f"Contact {SYNTHETIC_EMAIL} for the audit ledger.\n").encode(), kind="txt")
    _write(root, entries, "docs/beta_technology.md",
           b"# Beta technology notes\n\nMachine learning compiler algorithm network data "
           b"python testing.\n", kind="markdown")
    _write(root, entries, "docs/gamma_health.html",
           b"<html><body><h1>Gamma health</h1><p>Patient clinical diagnosis treatment "
           b"medical hospital therapy research.</p></body></html>", kind="html")
    _write(root, entries, "docs/delta_legal.csv",
           b"clause,court,regulation\ncontract,compliance,liability\nagreement,statute,civil\n",
           kind="csv")
    _write(root, entries, "docs/pii_fixture.txt",
           (f"Synthetic privacy fixture. Email {SYNTHETIC_EMAIL}. IBAN {SYNTHETIC_IBAN}. "
            f"Card {SYNTHETIC_CARD}. Phone {SYNTHETIC_PHONE}.\n").encode(), kind="pii")
    _write(root, entries, "docs/fr_note.txt",
           b"Le rapport financier trimestriel est pour la banque et le paiement de la "
           b"comptabilite et du revenu avec les taxes.\n", kind="multilingual")
    _write(root, entries, "docs/de_notiz.txt",
           b"Der technische Bericht ist fuer das Netzwerk und die Datenbank mit der "
           b"Software und dem Compiler.\n", kind="multilingual")

    # -- versions and duplicates ------------------------------------------
    _write(root, entries, "versions/report_v1.txt",
           b"Release report version one draft accounting revenue bank invoice.\n",
           kind="version")
    _write(root, entries, "versions/report_v2.txt",
           b"Release report version two final accounting revenue bank invoice audit.\n",
           kind="version")
    _write(root, entries, "duplicates/exact_a.txt",
           b"Exact duplicate payload: shared finance invoice bank revenue ledger.\n",
           kind="duplicate")
    _write(root, entries, "duplicates/exact_b.txt",
           b"Exact duplicate payload: shared finance invoice bank revenue ledger.\n",
           kind="duplicate")
    _write(root, entries, "near/near_a.txt",
           b"Near duplicate one: compiler algorithm network python testing module.\n",
           kind="near_duplicate")
    _write(root, entries, "near/near_b.txt",
           b"Near duplicate two: compiler algorithm network python testing modules and tools.\n",
           kind="near_duplicate")

    # -- rich formats ------------------------------------------------------
    _write(root, entries, "formats/sample.pdf", _minimal_pdf("Release PDF finance invoice"),
           kind="pdf")
    _write(root, entries, "formats/scanned.pdf", _scanned_pdf(), kind="pdf_scanned",
           expect="ocr_candidate")
    _write(root, entries, "formats/sample.docx", _docx("Release DOCX content career candidate"),
           kind="docx")
    _write(root, entries, "formats/sample.xlsx", _xlsx(), kind="xlsx")
    _write(root, entries, "formats/sample.odt", _odt("Release ODT legal contract clause"),
           kind="odt")
    _write(root, entries, "formats/sample.epub",
           _epub("Release EPUB health science chapter"), kind="epub")
    _write(root, entries, "formats/sample.eml",
           (f"From: Release Fixture <{SYNTHETIC_EMAIL}>\r\n"
            "To: Operator <operator@example.test>\r\n"
            "Subject: Release email fixture\r\n"
            "Date: Mon, 15 Jan 2024 09:00:00 +0000\r\n"
            "Message-ID: <release-fixture-1@example.test>\r\n\r\n"
            "Email body with career recruitment interview salary position.\r\n").encode(),
           kind="eml")
    _write(root, entries, "formats/sample.rtf",
           b"{\\rtf1\\ansi Release RTF fallback text finance invoice.}", kind="rtf")
    _write(root, entries, "formats/sample.msg", _msg_stub(), kind="msg_stub",
           expect="graceful")

    # -- archive ----------------------------------------------------------
    _write(root, entries, "archives/bundle.zip", _archive(), kind="archive")

    # -- hostile fixtures --------------------------------------------------
    _write(root, entries, "hostile/malformed.pdf", b"%PDF-1.4\nthis is not a real pdf\n%%EOF",
           kind="malformed_pdf", expect="graceful")
    _write(root, entries, "hostile/truncated.docx", b"PK\x03\x04truncated-not-a-docx",
           kind="malformed_docx", expect="graceful")
    _write(root, entries, "hostile/unsupported.xyz",
           bytes(range(256)) * 4, kind="unsupported", expect="unsupported")
    _write(root, entries, "hostile/unknown.bin", struct.pack(">I", 0xDEADBEEF) + b"\x00" * 32,
           kind="unsupported", expect="unsupported")

    # -- deterministic timelines ------------------------------------------
    for name, _kind, moment in (("docs/alpha_finance.txt", "txt", MTIMES["alpha"]),
                                ("docs/beta_technology.md", "markdown", MTIMES["beta"]),
                                ("docs/gamma_health.html", "html", MTIMES["gamma"]),
                                ("docs/delta_legal.csv", "csv", MTIMES["delta"])):
        _set_mtime(root / name, moment)

    return AcceptanceCorpus(root=root, entries=entries)


def write_manifest(corpus: AcceptanceCorpus, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corpus.manifest, indent=2), encoding="utf-8")
    return path
