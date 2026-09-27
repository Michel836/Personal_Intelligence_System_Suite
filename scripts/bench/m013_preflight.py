#!/usr/bin/env python3
"""M013 scale-preflight discovery (metadata only, read-only).

This tool mirrors the *production* scanner exclusion semantics from
``src/scanner/fast_engine.py`` as closely as possible, then produces the
aggregate evidence needed to select a 250k-500k eligible-file corpus.

Guarantees:
  * never opens source file contents (``os.scandir`` + ``lstat`` only);
  * never writes inside a scanned root;
  * never extracts archives;
  * bounded work via ``--max-files`` (marks ``truncated`` and stops).

The exclusion model is duplicated *on purpose* (it must run stand-alone before
any app import), but a regression test asserts it stays in sync with
``FastScannerEngine._skip_dirs`` / ``._skip_extensions``.
"""
from __future__ import annotations

import argparse
import json
import os
import stat as statmod
import time
from collections import Counter
from pathlib import Path

# --- mirrors src/scanner/fast_engine.py (keep in sync, see test_preflight) ---
SKIP_DIRS = {
    "windows", "program files", "program files (x86)",
    "programdata", "$recycle.bin", "system volume information",
    "windows.old", "recovery",
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox",
    "dist", "build",
    "coverage", ".coverage",
    ".cache",
}
SKIP_EXT = {
    ".dll", ".sys", ".exe", ".msi", ".tmp", ".log",
    ".cache", ".lock", ".pid", ".swp", ".~", ".lnk",
    ".bak", ".temp",
}
# ---------------------------------------------------------------------------

ARCHIVE_SUFFIXES = {
    ".zip": "ZIP", ".rar": "RAR", ".7z": "SEVENZIP",
    ".tar": "TAR", ".gz": "GZ", ".bz2": "BZ2", ".xz": "XZ",
    ".tgz": "TAR_GZ", ".tbz2": "TAR_BZ2", ".txz": "TAR_XZ",
    ".tar.gz": "TAR_GZ", ".tar.bz2": "TAR_BZ2", ".tar.xz": "TAR_XZ",
    ".zst": "ZSTD", ".lz4": "LZ4", ".z": "COMPRESS", ".cab": "CAB",
    ".iso": "ISO", ".apk": "APK", ".xapk": "XAPK", ".jar": "JAR",
    ".war": "WAR", ".ear": "EAR", ".whl": "WHEEL", ".deb": "DEB",
    ".rpm": "RPM", ".appimage": "APPIMAGE",
}

TEXT_EXT = {".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl",
            ".xml", ".yaml", ".yml", ".html", ".htm", ".xhtml", ".ini",
            ".cfg", ".conf", ".toml", ".tex", ".rtf", ".srt", ".vtt",
            ".po", ".properties", ".env", ".log"}
OFFICE_EXT = {".doc", ".docx", ".docm", ".xls", ".xlsx", ".xlsm", ".xlsb",
              ".ppt", ".pptx", ".pptm", ".odt", ".ods", ".odp", ".odg",
              ".pages", ".numbers", ".key", ".mm", ".vsd", ".vsdx",
              ".abw", ".wpd", ".one", ".pub"}
PDF_EXT = {".pdf"}
EMAIL_EXT = {".eml", ".msg", ".pst", ".ost", ".mbox", ".mbx", ".emlx"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
             ".webp", ".heic", ".heif", ".svg", ".ico", ".raw", ".cr2",
             ".nef", ".arw", ".dng", ".psd", ".xcf", ".tga", ".jfif"}
CODE_EXT = {".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
            ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs",
            ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".zsh", ".ps1",
            ".bat", ".cmd", ".sql", ".kt", ".kts", ".swift", ".scala",
            ".r", ".m", ".mm", ".lua", ".pl", ".pm", ".vue", ".svelte",
            ".css", ".scss", ".sass", ".less", ".ipynb", ".asm", ".s",
            ".v", ".vhd", ".vhdl", ".ex", ".exs", ".erl", ".clj", ".groovy",
            ".dart", ".fs", ".fsx", ".jl", ".nim", ".zig", ".sol"}
DATABASE_EXT = {".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".dbf",
                ".sqlite2", ".frm", ".myd", ".myi", ".db3"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
             ".wma", ".m4b", ".aiff", ".aif", ".ape", ".mid", ".midi"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv",
             ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".vob", ".ogv"}
BINARY_EXT = {".so", ".dylib", ".bin", ".img", ".dat", ".obb", ".wasm",
              ".class", ".o", ".a", ".lib", ".obj", ".pdb", ".node",
              ".crx", ".xpi", ".nupkg", ".snap", ".flatpak", ".pak"}


def category_for(name: str) -> str:
    lower = name.lower()
    for suffix, _fmt in ARCHIVE_SUFFIXES.items():
        if lower.endswith(suffix):
            return "archive"
    ext = os.path.splitext(lower)[1]
    if ext in PDF_EXT:
        return "pdf"
    if ext in OFFICE_EXT:
        return "office"
    if ext in EMAIL_EXT:
        return "email"
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    if ext in CODE_EXT:
        return "code"
    if ext in DATABASE_EXT:
        return "database"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    if ext in BINARY_EXT:
        return "binary"
    if ext == "":
        return "extensionless"
    return "other"


def archive_format(name: str) -> str | None:
    lower = name.lower()
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix):
            return ARCHIVE_SUFFIXES[suffix]
    return None


def skipped_dir(path_parts: tuple[str, ...]) -> bool:
    """Mirror FastScannerEngine._should_skip_directory (component match)."""
    parts = {p.lower() for p in path_parts}
    if parts & SKIP_DIRS:
        return True
    lowered = os.path.join(*path_parts).lower().replace("/", "\\")
    return "\\appdata\\local\\temp" in lowered


def skipped_file(name: str) -> bool:
    """Mirror FastScannerEngine._should_skip_file_fast."""
    if name.startswith("."):
        return True
    return os.path.splitext(name)[1].lower() in SKIP_EXT


def scan_root(root: str, *, max_files: int, top_level: bool = True) -> dict:
    root_path = Path(root)
    agg: dict = {
        "root": root,
        "exists": root_path.exists(),
        "truncated": False,
        "raw_regular_files": 0,
        "raw_dirs": 0,
        "symlink_files": 0,
        "symlink_dirs": 0,
        "special_files": 0,
        "permission_errors": 0,
        "excluded_dir_prunes": 0,
        "excluded_dir_files_estimate": 0,
        "hidden_files": 0,
        "ignored_ext_files": 0,
        "eligible_files": 0,
        "eligible_physical_files": 0,
        "eligible_bytes": 0,
        "raw_bytes": 0,
        "archives": 0,
        "archive_bytes": 0,
        "zero_byte": 0,
        "max_depth": 0,
        "unicode_names": 0,
        "deep_paths": 0,
        "largest": [],
        "devices": {},
        "ext_counts": Counter(),
        "ext_bytes": Counter(),
        "category_counts": Counter(),
        "category_bytes": Counter(),
        "archive_counts": Counter(),
        "archive_bytes_by_format": Counter(),
        "top_level": {},
        "elapsed_s": 0.0,
    }
    if not root_path.exists():
        return _finish(agg)

    try:
        base_dev = root_path.stat().st_dev
    except OSError:
        base_dev = None
    agg["base_dev"] = str(base_dev)

    largest: list[tuple[int, str]] = []
    stack: list[tuple[str, tuple[str, ...], int]] = [(str(root_path), (), 0)]
    scanned = 0
    while stack:
        dirpath, rel_parts, depth = stack.pop()
        check_parts = rel_parts if rel_parts else (os.path.basename(dirpath),)
        if skipped_dir(check_parts):
            agg["excluded_dir_prunes"] += 1
            continue
        agg["max_depth"] = max(agg["max_depth"], depth)
        try:
            entries = list(os.scandir(dirpath))
        except (PermissionError, OSError):
            agg["permission_errors"] += 1
            continue
        for entry in entries:
            if scanned >= max_files:
                agg["truncated"] = True
                stack.clear()
                break
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                agg["permission_errors"] += 1
                continue
            mode = st.st_mode
            if statmod.S_ISLNK(mode):
                if entry.is_dir(follow_symlinks=False):
                    agg["symlink_dirs"] += 1
                else:
                    agg["symlink_files"] += 1
                    agg["raw_regular_files"] += 1
                continue
            if statmod.S_ISDIR(mode):
                agg["raw_dirs"] += 1
                stack.append((entry.path, (*rel_parts, entry.name), depth + 1))
                continue
            if not statmod.S_ISREG(mode):
                agg["special_files"] += 1
                continue

            scanned += 1
            name = entry.name
            size = st.st_size
            agg["raw_regular_files"] += 1
            agg["raw_bytes"] += size
            if st.st_size == 0:
                agg["zero_byte"] += 1
            if any(ord(c) > 127 for c in name):
                agg["unicode_names"] += 1
            if depth >= 8:
                agg["deep_paths"] += 1
            agg["devices"][str(st.st_dev)] = agg["devices"].get(str(st.st_dev), 0) + 1
            largest.append((size, name))
            if len(largest) > 20:
                largest.sort(reverse=True)
                del largest[20:]

            fmt = archive_format(name)
            if fmt:
                agg["archives"] += 1
                agg["archive_bytes"] += size
                agg["archive_counts"][fmt] += 1
                agg["archive_bytes_by_format"][fmt] += size

            if skipped_file(name):
                if name.startswith("."):
                    agg["hidden_files"] += 1
                else:
                    agg["ignored_ext_files"] += 1
                continue

            agg["eligible_files"] += 1
            agg["eligible_physical_files"] += 1
            agg["eligible_bytes"] += size
            ext = os.path.splitext(name)[1].lower() or "<none>"
            agg["ext_counts"][ext] += 1
            agg["ext_bytes"][ext] += size
            cat = category_for(name)
            agg["category_counts"][cat] += 1
            agg["category_bytes"][cat] += size
            if top_level:
                first = rel_parts[0] if rel_parts else "<root-files>"
                tl = agg["top_level"].setdefault(first, {
                    "eligible_files": 0, "eligible_bytes": 0,
                    "archives": 0, "dirs": 0,
                })
                tl["eligible_files"] += 1
                tl["eligible_bytes"] += size
                if fmt:
                    tl["archives"] += 1
        if top_level:
            first = rel_parts[0] if rel_parts else "<root-files>"
            tl = agg["top_level"].setdefault(first, {
                "eligible_files": 0, "eligible_bytes": 0,
                "archives": 0, "dirs": 0,
            })
            tl["dirs"] += 1

    agg["largest"] = [{"name": n, "size": s} for s, n in sorted(largest, reverse=True)]
    return _finish(agg)


CANONICAL_FORMATS = {
    "ZIP", "SEVENZIP", "RAR", "TAR", "TAR_GZ", "TAR_BZ2",
    "TAR_XZ", "GZ", "BZ2", "XZ",
}


def _finish(agg: dict) -> dict:
    for key in ("ext_counts", "ext_bytes", "category_counts", "category_bytes",
                "archive_counts", "archive_bytes_by_format"):
        agg[key] = dict(agg[key].most_common())
    agg["canonical_archives"] = sum(
        v for k, v in agg["archive_counts"].items() if k in CANONICAL_FORMATS
    )
    agg["canonical_archive_bytes"] = sum(
        v for k, v in agg["archive_bytes_by_format"].items() if k in CANONICAL_FORMATS
    )
    if agg.get("base_dev") is not None:
        agg["mount_escape_files"] = sum(
            v for k, v in agg["devices"].items() if k != agg["base_dev"]
        )
    return agg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-files", type=int, default=1_500_000)
    parser.add_argument("--no-top-level", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    per_root = []
    for root in args.roots:
        t0 = time.perf_counter()
        res = scan_root(root, max_files=args.max_files, top_level=not args.no_top_level)
        res["elapsed_s"] = round(time.perf_counter() - t0, 3)
        per_root.append(res)
        print(json.dumps({  # noqa: T201
            "root": root,
            "eligible_physical": res["eligible_physical_files"],
            "eligible_bytes": res["eligible_bytes"],
            "archives": res["archives"],
            "truncated": res["truncated"],
            "elapsed_s": res["elapsed_s"],
        }))

    aggregate = {
        "roots": args.roots,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "max_files": args.max_files,
        "per_root": per_root,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(aggregate, fh, ensure_ascii=False, indent=2)
    print(f"wrote {out_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
