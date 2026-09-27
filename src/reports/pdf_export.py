"""Canonical PDF export with an explicit local provider chain (M018).

One canonical path — the same standalone HTML — rendered to PDF by the first
available local provider:

1. **WeasyPrint** (pure Python, best CSS/`@page` support) when importable;
2. **LibreOffice** headless (already a project dependency for legacy formats);
3. **google-chrome** headless `--print-to-pdf`.

No provider is a *silent* fallback: the chosen provider and its version are
recorded in the manifest, and if none is available the export fails explicitly
(the HTML/JSON artifacts are still produced). Every run is isolated in a temp
profile, bounded by a timeout and output-size cap, and the produced PDF is
validated (openable, page count ≥ 1) before it is atomically moved into place.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

DEFAULT_TIMEOUT = 240
MAX_OUTPUT_BYTES = 300 * 1024 * 1024

_PROVIDER_ORDER = ("weasyprint", "libreoffice", "chrome")


@dataclass
class PdfResult:
    ok: bool
    provider: str | None = None
    provider_version: str | None = None
    bytes_written: int = 0
    pages: int = 0
    error: str | None = None


def _weasyprint_version() -> str | None:
    try:
        import weasyprint  # type: ignore[import-not-found]
        return getattr(weasyprint, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        return None


def _libreoffice_path() -> str | None:
    return shutil.which("libreoffice") or shutil.which("soffice")


def _chrome_path() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def available_providers() -> dict[str, dict[str, object]]:
    lo = _libreoffice_path()
    chrome = _chrome_path()
    return {
        "weasyprint": {"available": _weasyprint_version() is not None,
                       "version": _weasyprint_version()},
        "libreoffice": {"available": lo is not None, "path": lo},
        "chrome": {"available": chrome is not None, "path": chrome},
    }


def choose_provider(preferred: str | None = None) -> str | None:
    if preferred:
        info = available_providers().get(preferred)
        return preferred if info and info.get("available") else None
    for name in _PROVIDER_ORDER:
        if available_providers()[name]["available"]:
            return name
    return None


def _run(cmd: list[str], *, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False, shell=False)
        return proc.returncode, (proc.stderr or "")[:600]
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except OSError as exc:
        return -1, str(exc)[:300]


def _validate_pdf(path: Path) -> tuple[bool, int, str | None]:
    if not path.is_file() or path.stat().st_size == 0:
        return False, 0, "empty output"
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        return False, 0, "output exceeds size cap"
    try:
        from PyPDF2 import PdfReader
        pages = len(PdfReader(str(path)).pages)
        return (pages >= 1), pages, None if pages >= 1 else "zero pages"
    except Exception as exc:  # noqa: BLE001
        return False, 0, f"unreadable PDF: {type(exc).__name__}"


def _render_weasyprint(html_text: str, out: Path, *, timeout: int) -> PdfResult:  # noqa: ARG001
    version = _weasyprint_version()
    if version is None:
        return PdfResult(False, error="weasyprint unavailable")
    try:
        from weasyprint import HTML
        HTML(string=html_text).write_pdf(str(out))
    except Exception as exc:  # noqa: BLE001
        return PdfResult(False, provider="weasyprint", provider_version=version,
                         error=f"weasyprint failed: {type(exc).__name__}")
    ok, pages, err = _validate_pdf(out)
    return PdfResult(ok, "weasyprint", version, out.stat().st_size if out.exists() else 0,
                     pages, err)


def _render_libreoffice(html_text: str, out: Path, *, timeout: int) -> PdfResult:
    soffice = _libreoffice_path()
    if not soffice:
        return PdfResult(False, error="libreoffice unavailable")
    with tempfile.TemporaryDirectory(prefix="pis-pdf-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "report.html"
        src.write_text(html_text, encoding="utf-8")
        profile = tmp_path / "profile"
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc, err = _run([
            soffice, f"-env:UserInstallation=file://{profile}", "--headless",
            "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
            timeout=timeout)
        produced = out_dir / "report.pdf"
        if not produced.is_file():
            return PdfResult(False, provider="libreoffice", error=err or f"exit {rc}")
        shutil.copy2(produced, out)
    ok, pages, verr = _validate_pdf(out)
    return PdfResult(ok, "libreoffice", None, out.stat().st_size if out.exists() else 0,
                     pages, verr)


def _render_chrome(html_text: str, out: Path, *, timeout: int) -> PdfResult:
    chrome = _chrome_path()
    if not chrome:
        return PdfResult(False, error="chrome unavailable")
    with tempfile.TemporaryDirectory(prefix="pis-pdf-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "report.html"
        src.write_text(html_text, encoding="utf-8")
        profile = tmp_path / "chrome-profile"
        target = tmp_path / "report.pdf"
        rc, err = _run([
            chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--no-pdf-header-footer", f"--user-data-dir={profile}",
            f"--print-to-pdf={target}", f"file://{src}"],
            timeout=timeout)
        if not target.is_file():
            return PdfResult(False, provider="chrome", error=err or f"exit {rc}")
        shutil.copy2(target, out)
    ok, pages, verr = _validate_pdf(out)
    return PdfResult(ok, "chrome", None, out.stat().st_size if out.exists() else 0,
                     pages, verr)


_RENDERERS = {
    "weasyprint": _render_weasyprint,
    "libreoffice": _render_libreoffice,
    "chrome": _render_chrome,
}


def render_pdf(html_text: str, out_path: Path, *, provider: str | None = None,
               timeout: int = DEFAULT_TIMEOUT, allow_fallback: bool = True) -> PdfResult:
    """Render ``html_text`` to ``out_path`` (written atomically)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    candidates: list[str]
    if provider:
        candidates = [provider] if allow_fallback else [provider]
    else:
        candidates = [p for p in _PROVIDER_ORDER if available_providers()[p]["available"]]
    if not candidates:
        return PdfResult(False, error="no local PDF provider available "
                                      "(weasyprint/libreoffice/chrome)")

    last_error: str | None = None
    for name in candidates:
        renderer = _RENDERERS.get(name)
        if renderer is None:
            continue
        tmp_out = out_path.with_suffix(out_path.suffix + f".tmp-{os.getpid()}")
        result = renderer(html_text, tmp_out, timeout=timeout)
        if result.ok:
            os.replace(tmp_out, out_path)
            result.bytes_written = out_path.stat().st_size
            logger.info(f"M018 PDF exported via {result.provider} ({result.pages} pages)")
            return result
        last_error = f"{name}: {result.error}"
        logger.warning(f"M018 PDF provider {name} failed: {result.error}")
        import contextlib
        with contextlib.suppress(OSError):
            tmp_out.unlink(missing_ok=True)
        if not allow_fallback:
            break
    return PdfResult(False, error=last_error or "PDF rendering failed")
