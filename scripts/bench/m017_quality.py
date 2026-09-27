#!/usr/bin/env python3
"""M017 extraction *quality* benchmark (aggregate only).

Two independent layers:

1. **Synthetic fidelity** — controlled fixtures with known tokens for EML
   (plain/HTML/nested), MSG (native CFB), EPUB and RTF. Each fixture must yield
   its token (recall) and must not leak attachment payloads.
2. **Real bounded sample** — a small read-only sample per legacy/email/EPUB/CHM
   extension from an existing trial DB, reporting success, non-empty text,
   mean characters and printable-ratio as a fidelity proxy. No filename or path
   is written to the report.

OCR character accuracy is measured on synthetic images via a similarity ratio.

No source file is modified. Output is a single aggregate JSON document.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import resource
import struct
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# --- synthetic CFB (regular FAT) builder, mirroring the unit-test fixture -----
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


def make_cfb(streams: dict[str, bytes]) -> bytes:
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
    struct.pack_into("<I", header, 56, 0)
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


# --- synthetic fidelity ------------------------------------------------------
def synthetic_fidelity(manager: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="pis-m017q-") as tmp:
        d = Path(tmp)

        plain = (b"From: a@b.com\r\nSubject: Plain\r\nMessage-ID: <p@x>\r\n\r\n"
                 b"EMLBODYTOKEN content.\r\n")
        (d / "p.eml").write_bytes(plain)

        html = (b"From: a@b.com\r\nSubject: Html\r\nMIME-Version: 1.0\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n\r\n"
                b"<html><body><p>EMLHTMLTOKEN content</p></body></html>")
        (d / "h.eml").write_bytes(html)

        nested = (b"From: a@b.com\r\nSubject: Nested\r\nMIME-Version: 1.0\r\n"
                  b'Content-Type: multipart/mixed; boundary="N"\r\n\r\n'
                  b"--N\r\nContent-Type: text/plain\r\n\r\nOUTERTOKEN\r\n"
                  b"--N\r\nContent-Type: message/rfc822\r\n\r\n"
                  b"From: i@b.com\r\nSubject: Inner\r\n\r\nNESTEDTOKEN\r\n--N--\r\n")
        (d / "n.eml").write_bytes(nested)

        attach = (b"From: a@b.com\r\nSubject: Attach\r\nMIME-Version: 1.0\r\n"
                  b'Content-Type: multipart/mixed; boundary="A"\r\n\r\n'
                  b"--A\r\nContent-Type: text/plain\r\n\r\nBODYTOKEN\r\n"
                  b"--A\r\nContent-Type: text/plain; name=\"s.txt\"\r\n"
                  b'Content-Disposition: attachment; filename="s.txt"\r\n\r\n'
                  b"SECRETATTACHMENT\r\n--A--\r\n")
        (d / "a.eml").write_bytes(attach)

        msg = make_cfb({"__substg1.0_0037001F": "MSGSUBJECTTOKEN".encode("utf-16-le"),
                        "__substg1.0_1000001F": "MSGBODYTOKEN".encode("utf-16-le")})
        (d / "m.msg").write_bytes(msg)

        with zipfile.ZipFile(d / "b.epub", "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("OEBPS/c.xhtml",
                        "<html><body><p>EPUBBODYTOKEN</p></body></html>")
        (d / "t.rtf").write_bytes(b"{\\rtf1\\ansi RTFBODYTOKEN world.\\par}")

        cases: list[tuple[str, Path, list[str], list[str]]] = [
            ("eml_plain", d / "p.eml", ["EMLBODYTOKEN"], []),
            ("eml_html", d / "h.eml", ["EMLHTMLTOKEN"], []),
            ("eml_nested", d / "n.eml", ["OUTERTOKEN", "NESTEDTOKEN"], []),
            ("eml_attachment", d / "a.eml", ["BODYTOKEN"], ["SECRETATTACHMENT"]),
            ("msg_cfb", d / "m.msg", ["MSGSUBJECTTOKEN", "MSGBODYTOKEN"], []),
            ("epub", d / "b.epub", ["EPUBBODYTOKEN"], []),
            ("rtf", d / "t.rtf", ["RTFBODYTOKEN"], []),
        ]
        for name, path, include, exclude in cases:
            res = manager.extract_single(path)
            text = res.content or ""
            row: dict[str, Any] = {
                "success": bool(res.success),
                "non_empty": bool(text.strip()),
                "token_recall": round(sum(1 for t in include if t in text) / len(include), 3),
                "chars": len(text),
            }
            leaked = [t for t in exclude if t in text]
            row["leaked_payload"] = bool(leaked)
            results[name] = row
    return results


# --- OCR character accuracy --------------------------------------------------
def ocr_accuracy() -> dict[str, Any]:
    from src.extractors import ocr
    if not ocr.tesseract_available():
        return {"available": False}
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return {"available": False}
    os.environ["PIS_OCR_ENABLED"] = "1"
    samples = ["INVOICE 2026 TOTAL", "FACTURE 2026 MONTANT", "RECHNUNG 2026 SUMME"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="pis-m017ocr-") as tmp:
        d = Path(tmp)
        for expected in samples:
            img = Image.new("RGB", (900, 120), "white")
            ImageDraw.Draw(img).text((20, 45), expected, fill="black")
            path = d / "x.png"
            img.save(path)
            res = ocr.ocr_file(path)
            got = " ".join((res.content or "").upper().split())
            ratio = difflib.SequenceMatcher(None, expected.upper(), got).ratio()
            rows.append({"success": bool(res.success), "ratio": round(ratio, 3),
                         "chars": len(got)})
    ratios = [r["ratio"] for r in rows]
    return {"available": True, "samples": rows,
            "mean_ratio": round(sum(ratios) / len(ratios), 3) if ratios else 0.0}


# --- real bounded sample -----------------------------------------------------
def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch.isprintable() or ch in "\n\t")
    return round(good / len(text), 3)


def real_sample(db_path: Path, manager: Any, per_ext: int) -> dict[str, Any]:
    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    table: dict[str, Any] = {}
    for ext in (".msg", ".eml", ".doc", ".xls", ".rtf", ".chm", ".epub"):
        rows = conn.execute(
            "SELECT path FROM files WHERE document_kind='PHYSICAL_FILE' AND extension=? "
            "AND COALESCE(state,'ACTIVE')='ACTIVE' LIMIT ?", (ext, int(per_ext))).fetchall()
        tested = success = non_empty = 0
        total_chars = 0
        ratios: list[float] = []
        for r in rows:
            p = Path(r["path"])
            if not p.is_file():
                continue
            tested += 1
            res = manager.extract_single(p)
            text = res.content or ""
            if res.success:
                success += 1
            if text.strip():
                non_empty += 1
                total_chars += len(text)
                ratios.append(_printable_ratio(text))
        if tested:
            table[ext] = {
                "tested": tested,
                "success": success,
                "non_empty": non_empty,
                "mean_chars": round(total_chars / max(1, non_empty), 1),
                "mean_printable_ratio": round(sum(ratios) / len(ratios), 3) if ratios else 0.0,
            }
    conn.close()
    return table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="existing trial DB (read-only sample)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-ext", type=int, default=20)
    ap.add_argument("--skip-ocr", action="store_true")
    args = ap.parse_args(argv)

    from src.extractors.manager import ExtractionManager

    manager = ExtractionManager(max_workers=1)
    t0 = time.perf_counter()
    report: dict[str, Any] = {
        "synthetic_fidelity": synthetic_fidelity(manager),
        "real_sample": real_sample(Path(args.db), manager, args.per_ext),
        "ocr_accuracy": {} if args.skip_ocr else ocr_accuracy(),
        "wall_s": 0.0,
        "peak_rss_mb": 0.0,
    }
    report["wall_s"] = round(time.perf_counter() - t0, 2)
    report["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
