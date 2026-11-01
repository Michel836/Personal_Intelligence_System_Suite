#!/usr/bin/env python3
"""Build the user guide PDF from the canonical Markdown source.

Pipeline (reproducible, no network):

    docs/Guide_Utilisation_36TB_Intelligence.md
        -> pandoc (GitHub-flavoured Markdown -> standalone HTML)
        -> Chrome headless (print to A4 PDF)
        -> docs/Guide_36TB_Intelligence.pdf

If Chrome is unavailable, WeasyPrint is used when installed. The HTML/CSS is
self-contained (system fonts only), so the PDF can be rebuilt offline.

Usage:
    python scripts/build_user_guide.py
    python scripts/build_user_guide.py --check
    python scripts/build_user_guide.py --html /tmp/guide.html --keep-html
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "Guide_Utilisation_36TB_Intelligence.md"
OUTPUT = ROOT / "docs" / "Guide_36TB_Intelligence.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
html { font-size: 10.5pt; }
body {
  font-family: "DejaVu Sans", "Liberation Sans", "Noto Sans", Arial, sans-serif;
  color: #1f2933; line-height: 1.55; max-width: none; margin: 0;
}
h1, h2, h3, h4 { font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif; }
h1 {
  font-size: 22pt; color: #0b4f6c; border-bottom: 3px solid #0b4f6c;
  padding-bottom: 6px; margin: 0 0 14px 0; page-break-before: always;
}
h1:first-of-type { page-break-before: avoid; }
h2 {
  font-size: 15pt; color: #0b4f6c; margin-top: 22px;
  border-bottom: 1px solid #c9d6df; padding-bottom: 3px;
}
h3 { font-size: 12.5pt; color: #14532d; margin-top: 18px; }
h4 { font-size: 11pt; color: #334155; margin-top: 14px; }
p, li { orphans: 3; widows: 3; }
a { color: #0b5f8a; text-decoration: none; }
code {
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 9pt; background: #f1f5f9; padding: 1px 4px; border-radius: 3px;
}
pre {
  background: #0f172a; color: #e2e8f0; padding: 10px 12px; border-radius: 6px;
  font-size: 8.8pt; line-height: 1.4; white-space: pre-wrap;
  word-break: break-word; page-break-inside: avoid;
}
pre code { background: transparent; color: inherit; padding: 0; }
blockquote {
  border-left: 4px solid #38bdf8; background: #f0f9ff; margin: 10px 0;
  padding: 8px 12px; color: #0c4a6e;
}
table {
  border-collapse: collapse; width: 100%; margin: 10px 0;
  font-size: 9pt; page-break-inside: avoid;
}
th { background: #0b4f6c; color: #ffffff; text-align: left; }
th, td { border: 1px solid #cbd5e1; padding: 5px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
hr { border: 0; border-top: 1px solid #cbd5e1; margin: 18px 0; }
ul, ol { padding-left: 20px; }
img { max-width: 100%; }
"""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _find_pandoc() -> str | None:
    return shutil.which("pandoc")


def check() -> int:
    pandoc = _find_pandoc()
    chrome = _find_chrome()
    weasy = None
    try:
        import weasyprint  # noqa: F401

        weasy = "weasyprint"
    except Exception:  # noqa: BLE001
        weasy = None
    print(f"source:   {SOURCE} ({'ok' if SOURCE.is_file() else 'MISSING'})")
    print(f"pandoc:   {pandoc or 'MISSING'}")
    print(f"chrome:   {chrome or 'MISSING'}")
    print(f"weasy:    {weasy or 'not installed'}")
    ok = SOURCE.is_file() and pandoc is not None and (chrome is not None or weasy is not None)
    return 0 if ok else 1


def build(html_out: Path | None = None, keep_html: bool = False) -> int:
    if not SOURCE.is_file():
        sys.stderr.write(f"missing source: {SOURCE}\n")
        return 2
    pandoc = _find_pandoc()
    if pandoc is None:
        sys.stderr.write("pandoc is required (apt install pandoc)\n")
        return 2

    work = Path(tempfile.mkdtemp(prefix="pis-guide-"))
    css_path = work / "guide.css"
    css_path.write_text(CSS, encoding="utf-8")
    target_html = html_out or (work / "guide.html")

    command = [
        pandoc, str(SOURCE),
        "--from", "gfm+definition_lists+footnotes",
        "--to", "html5",
        "--standalone",
        "--metadata", "title=Guide d'Utilisation - 36TB Intelligence",
        "--metadata", "lang=fr",
        "--toc", "--toc-depth=2",
        "--css", str(css_path),
        "--embed-resources",
        "-o", str(target_html),
    ]
    result = _run(command)
    if result.returncode != 0:
        # Older pandoc (<3.0) has no --embed-resources.
        command[command.index("--embed-resources")] = "--self-contained"
        result = _run(command)
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-2000:] + "\n")
        return 2

    chrome = _find_chrome()
    if chrome is not None:
        pdf_cmd = [
            chrome, "--headless", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUTPUT}",
            f"file://{target_html.resolve()}",
        ]
        result = _run(pdf_cmd)
        if result.returncode != 0:
            sys.stderr.write(result.stderr[-2000:] + "\n")
            # Retry without the header/footer flag (older Chrome).
            pdf_cmd.remove("--no-pdf-header-footer")
            result = _run(pdf_cmd)
    else:
        try:
            from weasyprint import HTML  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            sys.stderr.write("no Chrome and no WeasyPrint available\n")
            return 2
        HTML(filename=str(target_html)).write_pdf(str(OUTPUT))

    if result.returncode != 0 or not OUTPUT.is_file():
        sys.stderr.write("PDF generation failed\n")
        return 2

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"built: {OUTPUT} ({size_mb:.2f} MB)")
    if html_out is not None and keep_html:
        print(f"html:  {target_html}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check tools and source only")
    parser.add_argument("--html", default=None, help="write the intermediate HTML here")
    parser.add_argument("--keep-html", action="store_true", help="keep HTML next to --html")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    html_out = Path(args.html) if args.html else None
    return build(html_out=html_out, keep_html=args.keep_html)


if __name__ == "__main__":
    raise SystemExit(main())
