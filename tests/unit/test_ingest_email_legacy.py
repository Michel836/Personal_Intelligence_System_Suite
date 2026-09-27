"""Email / MSG-CFB / EPUB / legacy extraction tests (M017)."""
from __future__ import annotations

import struct
import zipfile

import pytest

from src.extractors.manager import ExtractionManager
from src.ingest.cfb import read_cfb_streams


# --- minimal CFB builder (regular FAT; validates the parser mechanics) -------
def _dir_entry(name: str, etype: int, start: int, size: int) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00"
    name_len = min(len(raw), 64)
    e = bytearray(128)
    e[0:64] = raw[:64].ljust(64, b"\x00")
    struct.pack_into("<H", e, 64, name_len)
    e[66] = etype
    struct.pack_into("<I", e, 116, start)
    struct.pack_into("<Q", e, 120, size)
    return bytes(e)


def make_cfb(streams: dict) -> bytes:
    sector = 512
    entries = [_dir_entry("Root Entry", 5, 0xFFFFFFFE, 0)]
    fat = {0: 0xFFFFFFFD, 1: 0xFFFFFFFE}
    blocks = []
    next_sector = 2
    for name, data in streams.items():
        nsec = max(1, (len(data) + sector - 1) // sector)
        start = next_sector
        for k in range(nsec):
            fat[next_sector] = next_sector + 1 if k < nsec - 1 else 0xFFFFFFFE
            next_sector += 1
        entries.append(_dir_entry(name, 2, start, len(data)))
        blocks.append(data)
    header = bytearray(sector)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 24, 0x003E)
    struct.pack_into("<H", header, 26, 3)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<I", header, 40, 1)
    struct.pack_into("<I", header, 44, 1)
    struct.pack_into("<I", header, 48, 1)
    struct.pack_into("<I", header, 56, 0)  # mini cutoff 0 -> regular FAT
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)
    struct.pack_into("<I", header, 64, 0)
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)
    struct.pack_into("<I", header, 72, 0)
    for i in range(109):
        struct.pack_into("<I", header, 76 + 4 * i, 0 if i == 0 else 0xFFFFFFFF)
    fat_bytes = bytearray(sector)
    for i in range(sector // 4):
        struct.pack_into("<I", fat_bytes, 4 * i, fat.get(i, 0xFFFFFFFF))
    dir_bytes = bytearray(sector)
    for i, e in enumerate(entries[: sector // 128]):
        dir_bytes[i * 128:(i + 1) * 128] = e
    out = bytearray(header) + bytes(fat_bytes) + bytes(dir_bytes)
    for data in blocks:
        out += data + b"\x00" * ((-len(data)) % sector)
    return bytes(out)


def test_cfb_reader_roundtrip(tmp_path) -> None:
    cfb = make_cfb({"__substg1.0_0037001F": "Bonsoir".encode("utf-16-le"),
                    "__substg1.0_1000001F": "Corps".encode("utf-16-le")})
    p = tmp_path / "x.msg"
    p.write_bytes(cfb)
    streams = read_cfb_streams(p)
    assert streams["__substg1.0_0037001F"].decode("utf-16-le") == "Bonsoir"
    assert streams["__substg1.0_1000001F"].decode("utf-16-le") == "Corps"


def test_msg_extractor_with_cfb(tmp_path) -> None:
    cfb = make_cfb({"__substg1.0_0037001F": "Sujet".encode("utf-16-le"),
                    "__substg1.0_1000001F": "Le corps".encode("utf-16-le"),
                    "__substg1.0_0C1A001F": "Alice".encode("utf-16-le")})
    p = tmp_path / "m.msg"
    p.write_bytes(cfb)
    res = ExtractionManager(1).extract_single(p)
    assert res.success and "Sujet" in res.content and "Le corps" in res.content
    assert res.metadata.get("subject") == "Sujet"


def test_eml_plain_html_multipart_and_attachment(tmp_path) -> None:
    mgr = ExtractionManager(1)
    plain = (b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Hello\r\nMessage-ID: <1@b>\r\n"
             b"In-Reply-To: <0@b>\r\n\r\nBody text.\r\n")
    p = tmp_path / "a.eml"
    p.write_bytes(plain)
    r = mgr.extract_single(p)
    assert r.success and "Body text." in r.content and r.metadata["message_id"] == "<1@b>"

    multi = (b"From: x@y.com\r\nSubject: Multi\r\nMIME-Version: 1.0\r\n"
             b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
             b"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPart one.\r\n"
             b"--B\r\nContent-Type: text/plain; name=\"file.txt\"\r\n"
             b'Content-Disposition: attachment; filename="file.txt"\r\n\r\nSECRET\r\n--B--\r\n')
    p2 = tmp_path / "m.eml"
    p2.write_bytes(multi)
    r2 = mgr.extract_single(p2)
    assert r2.success and "Part one." in r2.content and "SECRET" not in r2.content
    assert r2.metadata["attachments"] and r2.metadata["attachments"][0]["filename"] == "file.txt"
    # a single traversal must not record the same attachment twice
    assert len(r2.metadata["attachments"]) == 1

    # nested message/rfc822 bodies are preserved (bounded), not dropped
    nested = (b"From: a@b.com\r\nSubject: Outer\r\nMIME-Version: 1.0\r\n"
              b'Content-Type: multipart/mixed; boundary="OUT"\r\n\r\n'
              b"--OUT\r\nContent-Type: text/plain\r\n\r\nOuter body.\r\n"
              b"--OUT\r\nContent-Type: message/rfc822\r\n\r\n"
              b"From: inner@b.com\r\nSubject: Inner\r\n\r\nInner body.\r\n"
              b"--OUT--\r\n")
    p3 = tmp_path / "n.eml"
    p3.write_bytes(nested)
    r3 = mgr.extract_single(p3)
    assert r3.success and r3.metadata["nested"] == 1
    assert "Outer body." in r3.content and "Inner body." in r3.content


def test_eml_html_and_charset(tmp_path) -> None:
    mgr = ExtractionManager(1)
    body = "Café résumé".encode("latin-1")
    eml = (b"From: x@y.com\r\nSubject: H\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n" + body + b"\r\n")
    p = tmp_path / "c.eml"
    p.write_bytes(eml)
    r = mgr.extract_single(p)
    assert r.success and "Café" in r.content

    html = (b"From: x@y.com\r\nSubject: H2\r\nMIME-Version: 1.0\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n\r\n"
            b"<html><body><p>Hello <b>world</b></p></body></html>")
    p2 = tmp_path / "h.eml"
    p2.write_bytes(html)
    r2 = mgr.extract_single(p2)
    assert r2.success and "Hello" in r2.content and "world" in r2.content and "<b>" not in r2.content


def test_epub_extraction(tmp_path) -> None:
    p = tmp_path / "b.epub"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/content.opf", "<package><metadata><dc:title>T</dc:title></metadata></package>")
        zf.writestr("OEBPS/c.xhtml", "<html><body><p>Hello epub.</p></body></html>")
    res = ExtractionManager(1).extract_single(p)
    assert res.success and "Hello epub." in res.content and res.metadata["title"] == "T"


def test_epub_entry_size_guard(tmp_path, monkeypatch) -> None:
    from src.extractors import epub_extractor
    monkeypatch.setattr(epub_extractor, "MAX_ENTRY_BYTES", 10)
    p = tmp_path / "big.epub"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/c.xhtml",
                    "<html><body><p>" + "BOOM" * 500 + "</p></body></html>")
    res = ExtractionManager(1).extract_single(p)
    # The oversized entry is skipped rather than read into memory.
    assert res.success and not (res.content or "").strip()


def test_rtf_via_unrtf(tmp_path) -> None:
    from src.ingest import tools
    if not tools.available("unrtf"):
        pytest.skip("unrtf not installed")
    p = tmp_path / "t.rtf"
    p.write_bytes(b"{\\rtf1\\ansi Hello RTF world.\\par Second line.}")
    res = ExtractionManager(1).extract_single(p)
    assert res.success and "Hello RTF world." in res.content


def test_legacy_missing_dependency_is_explicit(tmp_path, monkeypatch) -> None:
    from src.extractors import legacy_extractor
    monkeypatch.setattr(legacy_extractor.tools, "available", lambda _name: False)
    p = tmp_path / "x.wpd"
    p.write_bytes(b"not really wpd")
    res = ExtractionManager(1).extract_single(p)
    assert not res.success and "unsupported dependency" in (res.error or "").lower()


def test_capability_matrix_reports_missing() -> None:
    from src.ingest.capabilities import capability_matrix
    matrix = capability_matrix()
    formats = {f["format"]: f["status"] for f in matrix["formats"]}
    assert formats["PDF"] == "SUPPORTED"
    assert formats["WordPerfect"] == "DEFERRED"
    assert matrix["optional_dependencies"]["readpst"]["available"] is False
