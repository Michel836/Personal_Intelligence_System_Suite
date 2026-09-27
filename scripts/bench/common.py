# ruff: noqa
"""Shared utilities for the M010-P performance benchmark harness.

Design goals:

* reproducible: every benchmark records the machine-load conditions;
* bounded: synthetic corpora live under a temporary directory and are removed;
* non-invasive: never touches the real user index (``PIS_DB_PATH`` is forced to
  a temp path by each benchmark).

Nothing here is imported by production code.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Machine profile
# ---------------------------------------------------------------------------


def _run(cmd: List[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except Exception:
        return ""


def cpu_model() -> str:
    out = _run(["bash", "-lc", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2"])
    return out.strip() or "unknown"


def gpu_profile() -> Dict[str, Any]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return {"available": False}
    first = out.splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    return {
        "available": True,
        "name": parts[0],
        "vram_total_mb": int(parts[1]),
        "vram_used_mb": int(parts[2]),
        "utilization_pct": int(parts[3]),
    }


def read_proc_stat() -> Tuple[int, int, int]:
    """Return (total_jiffies, idle_jiffies, iowait_jiffies)."""
    with open("/proc/stat") as fh:
        first = fh.readline().split()
    values = [int(v) for v in first[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    iowait = values[4] if len(values) > 4 else 0
    return total, idle, iowait


def load_conditions() -> Dict[str, Any]:
    """Snapshot of the machine-load conditions at the start of a benchmark."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        mem = {
            "total_gb": round(vm.total / 1e9, 1),
            "used_gb": round((vm.total - vm.available) / 1e9, 1),
            "available_gb": round(vm.available / 1e9, 1),
        }
        swap = {"total_gb": round(sm.total / 1e9, 1), "used_gb": round(sm.used / 1e9, 1)}
    except Exception:
        mem, swap = {}, {}
    try:
        load1, load5, load15 = os.getloadavg()
        load = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except OSError:
        load = []
    # Top CPU consumers (informational only; never killed).
    top: List[Dict[str, Any]] = []
    try:
        import psutil

        procs = sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]),
            key=lambda p: (p.info.get("cpu_percent") or 0.0),
            reverse=True,
        )
        for p in procs[:5]:
            info = p.info
            top.append({
                "pid": info.get("pid"),
                "name": info.get("name"),
                "cpu": info.get("cpu_percent"),
                "rss_mb": round((info.get("memory_info").rss if info.get("memory_info") else 0) / 1e6, 1),
            })
    except Exception:
        pass
    return {
        "cpu_model": cpu_model(),
        "logical_cpus": os.cpu_count(),
        "loadavg": load,
        "mem": mem,
        "swap": swap,
        "gpu": gpu_profile(),
        "top_cpu_processes": top,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Resource sampling
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    wall: float = 0.0
    cpu_pct: float = 0.0
    rss_mb: float = 0.0
    read_mb: float = 0.0
    write_mb: float = 0.0


class ResourceSampler:
    """Sample process CPU/RSS/IO and system iowait around a block of work.

    ``cpu_pct`` is normalised to 100% == one core (psutil convention), so the
    reported value can exceed 100% for multi-threaded work. ``iowait`` is a
    system-wide delta over the measured interval.
    """

    def __init__(self) -> None:
        self._proc = None
        try:
            import psutil

            self._proc = psutil.Process(os.getpid())
            self._proc.cpu_percent(None)
        except Exception:
            self._proc = None
        self._t0 = 0.0
        self._stat0: Optional[Tuple[int, int, int]] = None
        self._io0 = None
        self.sample = Sample()

    def __enter__(self) -> "ResourceSampler":
        self._t0 = time.perf_counter()
        self._stat0 = read_proc_stat()
        if self._proc is not None:
            try:
                self._io0 = self._proc.io_counters()
            except Exception:
                self._io0 = None
        return self

    def __exit__(self, *exc) -> bool:
        wall = time.perf_counter() - self._t0
        cpu = 0.0
        rss = 0.0
        read_mb = write_mb = 0.0
        if self._proc is not None:
            try:
                cpu = self._proc.cpu_percent(None)
            except Exception:
                cpu = 0.0
            try:
                rss = self._proc.memory_info().rss / 1e6
            except Exception:
                rss = 0.0
            try:
                io = self._proc.io_counters()
                if self._io0 is not None:
                    read_mb = (io.read_bytes - self._io0.read_bytes) / 1e6
                    write_mb = (io.write_bytes - self._io0.write_bytes) / 1e6
            except Exception:
                pass
        iowait = 0.0
        if self._stat0 is not None:
            total1, _idle1, iowait1 = read_proc_stat()
            dtotal = total1 - self._stat0[0]
            if dtotal > 0:
                iowait = round((iowait1 - self._stat0[2]) / dtotal * 100, 2)
        nproc = os.cpu_count() or 1
        self.sample = Sample(wall=wall, cpu_pct=cpu, rss_mb=rss, read_mb=read_mb, write_mb=write_mb)
        self.iowait_pct = iowait
        self.cpu_cores = round(cpu / 100.0, 2)
        self.cpu_normalized = round(cpu / (100.0 * nproc) * 100, 2)
        return False


# ---------------------------------------------------------------------------
# Corpus generation
# ---------------------------------------------------------------------------

_TEXT_EXTS = [".txt", ".md", ".json", ".csv", ".html", ".py", ".log", ".xml"]
_DOC_EXTS = [".pdf", ".docx", ".xlsx", ".odt", ".ods"]


def generate_corpus(
    root: Path,
    count: int,
    *,
    seed: int = 1234,
    fanout: int = 20,
    max_depth: int = 5,
    with_documents: int = 0,
    doc_root: Optional[Path] = None,
) -> int:
    """Create ``count`` tiny files in a varied nested tree; return files created.

    ``with_documents`` additionally materialises that many representative
    extraction fixtures under ``doc_root`` (defaults to ``root/_docs``).
    """
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    dirs: List[Path] = [root]
    for _ in range(max_depth):
        for d in list(dirs):
            if rng.random() < 0.5:
                child = d / f"d{rng.randrange(1000):03d}"
                try:
                    child.mkdir(exist_ok=True)
                    dirs.append(child)
                except OSError:
                    pass
    created = 0
    written = 0
    i = 0
    while written < count:
        d = rng.choice(dirs)
        ext = rng.choice(_TEXT_EXTS)
        name = d / f"f{written:07d}_{i}{ext}"
        try:
            name.write_bytes(os.urandom(rng.randint(16, 256)))
            written += 1
        except OSError:
            pass
        i += 1
    created += written
    if with_documents:
        doc_root = doc_root or (root / "_docs")
        created += generate_documents(doc_root, with_documents, seed=seed)
    return created


def generate_documents(root: Path, count: int, *, seed: int = 99) -> int:
    """Create representative extraction fixtures (text-ish + office formats)."""
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    words = "le contrat de service prévoit une clause de confidentialité et un paiement".split()
    made = 0
    for i in range(count):
        body = " ".join(rng.choice(words) for _ in range(200))
        kind = i % 6
        try:
            if kind == 0:
                (root / f"doc{i}.txt").write_text(body, encoding="utf-8")
            elif kind == 1:
                (root / f"doc{i}.md").write_text(f"# Title {i}\n\n{body}", encoding="utf-8")
            elif kind == 2:
                (root / f"doc{i}.json").write_text(json.dumps({"id": i, "text": body}), encoding="utf-8")
            elif kind == 3:
                (root / f"doc{i}.csv").write_text("a,b,c\n" + "\n".join("1,2,3" for _ in range(50)), encoding="utf-8")
            elif kind == 4:
                (root / f"doc{i}.html").write_text(f"<html><body><p>{body}</p></body></html>", encoding="utf-8")
            else:
                (root / f"doc{i}.xml").write_text(f"<doc><body>{body}</body></doc>", encoding="utf-8")
            made += 1
        except OSError:
            pass
    return made


def make_pdf(path: Path, pages: int = 1, text: str = "contrat de service") -> None:
    """Create a minimal valid text PDF without external tools."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    stream = content.encode("latin-1")
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(pages))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for _ in range(pages):
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + pages * 2} 0 R >>".encode()
        )
    for p in range(pages):
        objs.append(
            f"<< /Length {len(stream) + p * 0} >>\nstream\n{content}\nendstream".encode("latin-1")
        )
    # Build xref
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def make_docx(path: Path, text: str = "contrat de service") -> None:
    import zipfile

    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", doc)


def make_xlsx(path: Path, text: str = "contrat") -> None:
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>{text}</t></is></c></row></sheetData></worksheet>',
        )


def make_odt(path: Path, text: str = "contrat de service") -> None:
    import zipfile

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text><text:p>{text}</text:p></office:text></office:body></office:document-content>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content)


def make_archive(path: Path, members: int = 100, *, payload: bytes = b"hello archive member") -> None:
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i in range(members):
            z.writestr(f"dir/file_{i:05d}.txt", payload)


def wipe(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def json_print(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


class Timer:
    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> bool:
        self.elapsed = time.perf_counter() - self.start
        return False
