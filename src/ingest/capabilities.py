"""Local format capability matrix + tool/dependency detection (M017).

Never claims support when the dependency is absent: each format is reported as
SUPPORTED, PARTIAL, OPTIONAL_DEPENDENCY_MISSING, DEFERRED or UNSUPPORTED.
"""
from __future__ import annotations

from typing import Any

from . import tools

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
OPTIONAL_DEPENDENCY_MISSING = "OPTIONAL_DEPENDENCY_MISSING"
DEFERRED = "DEFERRED"
UNSUPPORTED = "UNSUPPORTED"

#: (format, extensions, status-check callable / static status, notes, tools)
_FORMATS: list[dict[str, Any]] = [
    {"format": "PDF", "extensions": [".pdf"], "impl": "pdf_extractor", "base": SUPPORTED,
     "tools": []},
    {"format": "Office (modern)", "extensions": [".docx", ".xlsx", ".pptx"],
     "impl": "office_extractor", "base": SUPPORTED, "tools": []},
    {"format": "Office (legacy)", "extensions": [".doc", ".xls", ".ppt"],
     "impl": "legacy_extractor", "base": PARTIAL,
     "tools": ["antiword", "catdoc", "xls2csv", "catppt", "libreoffice"]},
    {"format": "RTF", "extensions": [".rtf"], "impl": "legacy_extractor", "base": PARTIAL,
     "tools": ["unrtf", "libreoffice"]},
    {"format": "WordPerfect", "extensions": [".wpd", ".wps"], "impl": "legacy_extractor",
     "base": DEFERRED, "tools": ["libreoffice"],
     "note": "absent in the M013 corpus (0 files); deferred, not dropped"},
    {"format": "OpenDocument", "extensions": [".odt", ".ods", ".odp"],
     "impl": "odf_extractor", "base": SUPPORTED, "tools": []},
    {"format": "Email EML", "extensions": [".eml"], "impl": "email_extractor",
     "base": SUPPORTED, "tools": []},
    {"format": "Email MHT", "extensions": [".mht", ".mhtml"], "impl": "email_extractor",
     "base": SUPPORTED, "tools": []},
    {"format": "Email MSG", "extensions": [".msg"], "impl": "email_extractor (native CFB)",
     "base": PARTIAL, "tools": [],
     "note": "native bounded CFB reader; extract_msg provides fuller fidelity if installed"},
    {"format": "PST/OST", "extensions": [".pst", ".ost"], "impl": "—", "base": UNSUPPORTED,
     "tools": ["readpst", "pypff"],
     "note": "requires readpst (libpff-tools) or the pypff Python package; absent here"},
    {"format": "MBOX", "extensions": [".mbox"], "impl": "—", "base": DEFERRED,
     "tools": [], "note": "absent in the M013 corpus"},
    {"format": "EPUB", "extensions": [".epub"], "impl": "epub_extractor (stdlib)",
     "base": SUPPORTED, "tools": []},
    {"format": "CHM", "extensions": [".chm"], "impl": "chm_extractor", "base": PARTIAL,
     "tools": ["7z"], "note": "HTML sections extracted via local 7z in temp space"},
    {"format": "OCR", "extensions": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"],
     "impl": "ocr (pytesseract)", "base": PARTIAL, "tools": ["tesseract"],
     "note": "opt-in via PIS_OCR_ENABLED; image-only PDFs preferred"},
    {"format": "Archives", "extensions": [".zip", ".tar", ".gz", ".7z", ".rar"],
     "impl": "archive indexer", "base": PARTIAL, "tools": ["7z", "unar"],
     "note": "RAR needs unrar/unar/7z"},
]


def _tool_status(name: str) -> dict[str, Any]:
    path = tools.which(name)
    return {"name": name, "available": path is not None, "path": path}


def capability_matrix() -> dict[str, Any]:
    from ..extractors.ocr import _installed_languages, ocr_enabled, tesseract_available
    formats = []
    for spec in _FORMATS:
        tool_info = [_tool_status(t) for t in spec["tools"]]
        missing = [t["name"] for t in tool_info if not t["available"]]
        status = spec["base"]
        if spec["base"] == PARTIAL and spec["tools"] and all(not t["available"] for t in tool_info):
            status = OPTIONAL_DEPENDENCY_MISSING
        formats.append({"format": spec["format"], "extensions": spec["extensions"],
                        "implementation": spec["impl"], "status": status,
                        "tools": tool_info, "missing_tools": missing,
                        "note": spec.get("note", "")})
    return {
        "formats": formats,
        "optional_dependencies": {
            "readpst": _tool_status("readpst"),
            "pypff": {"name": "pypff", "available": _import_ok("pypff")},
            "extract_msg": {"name": "extract_msg", "available": _import_ok("extract_msg")},
            "libreoffice": _tool_status("libreoffice"),
            "antiword": _tool_status("antiword"),
            "catdoc": _tool_status("catdoc"),
            "xls2csv": _tool_status("xls2csv"),
            "catppt": _tool_status("catppt"),
            "unrtf": _tool_status("unrtf"),
            "pandoc": _tool_status("pandoc"),
            "7z": _tool_status("7z"),
            "unar": _tool_status("unar"),
            "tesseract": _tool_status("tesseract"),
        },
        "ocr": {"enabled": ocr_enabled(), "available": tesseract_available(),
                "languages": sorted(_installed_languages())},
    }


def _import_ok(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False
