"""Safe, bounded execution of local conversion tools (M017).

Never uses a shell (no command injection), always a timeout, caps output size,
and runs on temp copies so source files are never modified. No cloud service.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 60
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    returncode: int = -1
    error: str | None = None
    timed_out: bool = False


def which(name: str) -> str | None:
    return shutil.which(name)


def available(name: str) -> bool:
    return which(name) is not None


def run_tool(args: list[str], *, timeout: int = DEFAULT_TIMEOUT,
             max_output: int = DEFAULT_MAX_BYTES, cwd: str | None = None,
             text_output: bool = True) -> ToolResult:
    """Run a local tool with a hard timeout and bounded output. No shell."""
    if not args or not which(args[0]):
        return ToolResult(False, error=f"tool unavailable: {args[0] if args else ''}")
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
            shell=False,  # explicit: never a shell
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
            return ToolResult(False, returncode=proc.returncode,
                              error=f"timeout after {timeout}s", timed_out=True)
    except FileNotFoundError:
        return ToolResult(False, error=f"tool not found: {args[0]}")
    if len(out) > max_output:
        out = out[:max_output]
    if text_output:
        decoded = out.decode("utf-8", "replace")
    else:
        decoded = out.decode("utf-8", "replace")
    if proc.returncode != 0:
        detail = err.decode("utf-8", "replace")[:300] if err else f"exit {proc.returncode}"
        return ToolResult(False, output=decoded, returncode=proc.returncode, error=detail)
    return ToolResult(True, output=decoded, returncode=proc.returncode)


def convert_with_libreoffice(src: Path, *, target: str = "txt:Text",
                             timeout: int = DEFAULT_TIMEOUT) -> ToolResult:
    """Convert a copy with headless LibreOffice into a controlled temp dir."""
    soffice = which("libreoffice") or which("soffice")
    if not soffice:
        return ToolResult(False, error="libreoffice unavailable")
    with tempfile.TemporaryDirectory(prefix="pis-convert-") as tmp:
        tmp_path = Path(tmp)
        copy = tmp_path / src.name
        try:
            shutil.copy2(src, copy)
        except OSError as exc:
            return ToolResult(False, error=f"copy failed: {exc}")
        res = run_tool([soffice, "--headless", "--convert-to", target, "--outdir", str(tmp_path), str(copy)],
                       timeout=timeout)
        if not res.ok:
            return ToolResult(False, error=res.error or "libreoffice conversion failed")
        produced = sorted(tmp_path.glob("*.txt"))
        if not produced:
            return ToolResult(False, error="libreoffice produced no text output")
        try:
            with produced[0].open("rb") as handle:
                data = handle.read(DEFAULT_MAX_BYTES)
        except OSError as exc:
            return ToolResult(False, error=f"read failed: {exc}")
        return ToolResult(True, output=data.decode("utf-8", "replace")[:DEFAULT_MAX_BYTES])


def run_filter_stdout(args: list[str], *, timeout: int = DEFAULT_TIMEOUT,
                      max_output: int = DEFAULT_MAX_BYTES) -> ToolResult:
    """Run a filter tool (antiword/catdoc/xls2csv/catppt/unrtf) on a temp copy."""
    src = Path(args[-1])
    if not src.exists():
        return ToolResult(False, error="source missing")
    with tempfile.TemporaryDirectory(prefix="pis-filter-") as tmp:
        copy = Path(tmp) / src.name
        try:
            shutil.copy2(src, copy)
        except OSError as exc:
            return ToolResult(False, error=f"copy failed: {exc}")
        return run_tool([*args[:-1], str(copy)], timeout=timeout, max_output=max_output)


def temp_cleanup_ok() -> bool:
    """Best-effort check that no leaked temp dirs remain (diagnostic)."""
    import glob
    return not (glob.glob("/tmp/pis-filter-*") or glob.glob("/tmp/pis-convert-*") or glob.glob("/tmp/pis-ocr-*"))
