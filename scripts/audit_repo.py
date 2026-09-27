#!/usr/bin/env python3
"""Static repository audit for Personal Intelligence System Suite.

This intentionally does not scan user data volumes. It audits the repository itself.
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def py_files() -> list[Path]:
    return sorted(
        p for base in (ROOT / "src", ROOT / "scripts", ROOT / "tests")
        if base.exists()
        for p in base.rglob("*.py")
    )


def parse_failures(files: list[Path]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            failures.append({"path": str(path.relative_to(ROOT)), "error": str(exc)})
    return failures


def markers(files: list[Path]) -> list[dict[str, object]]:
    # Markers are meaningful only in comments and string literals. Scanning raw
    # lines reported Streamlit ``placeholder=`` keyword arguments (and any
    # identifier named ``placeholder``) as debt, so tokenize the source instead.
    pattern = re.compile(r"\b(TODO|FIXME|XXX|HACK|placeholder|not implemented)\b", re.I)
    hits: list[dict[str, object]] = []
    for path in files:
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            token_stream = tokenize.generate_tokens(io.StringIO(source).readline)
            candidates = [
                (token.start[0], token.string)
                for token in token_stream
                if token.type in (tokenize.COMMENT, tokenize.STRING)
            ]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            candidates = list(enumerate(source.splitlines(), 1))
        for number, text in candidates:
            if pattern.search(text):
                hits.append({"path": str(path.relative_to(ROOT)), "line": number, "text": text.strip()[:240]})
    return hits


def oversized_python(files: list[Path], threshold: int = 50_000) -> list[dict[str, object]]:
    return [
        {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}
        for path in files
        if path.stat().st_size >= threshold
    ]


def declared_entrypoints() -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        for module, func in re.findall(r'=\s*"([A-Za-z0-9_.]+):([A-Za-z0-9_]+)"', text):
            module_path = ROOT / (module.replace(".", "/") + ".py")
            package_path = ROOT / module.replace(".", "/") / "__init__.py"
            checks.append({
                "kind": "pyproject-script",
                "target": f"{module}:{func}",
                "exists": module_path.exists() or package_path.exists(),
            })
    makefile = ROOT / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        for module in re.findall(r"uvicorn\s+([A-Za-z0-9_.]+):[A-Za-z0-9_]+", text):
            module_path = ROOT / (module.replace(".", "/") + ".py")
            checks.append({"kind": "makefile-uvicorn", "target": module, "exists": module_path.exists()})
    return checks


def backup_like_files() -> list[str]:
    patterns = ("*backup*", "*.bak", "*copy*", "*old*")
    found: set[str] = set()
    for pattern in patterns:
        for path in SRC.rglob(pattern):
            if path.is_file():
                found.add(str(path.relative_to(ROOT)))
    return sorted(found)


def main() -> int:
    files = py_files()
    report = {
        "python_files": len(files),
        "syntax_failures": parse_failures(files),
        "markers": markers(files),
        "oversized_python": oversized_python(files),
        "declared_entrypoints": declared_entrypoints(),
        "backup_like_files": backup_like_files(),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    hard_fail = bool(report["syntax_failures"]) or any(not item["exists"] for item in report["declared_entrypoints"])
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
