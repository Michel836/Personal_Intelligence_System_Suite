"""Cross-platform file/folder opening helpers (M012-B2).

The canonical app is Linux-first (Kubuntu) but should keep working on Windows
and macOS.  These helpers centralise the platform-specific command selection so
no UI module hard-codes ``explorer`` or ``os.startfile``.  Every call is
best-effort: a missing opener returns ``False`` and never raises.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def open_path(path: str | Path) -> bool:
    """Open *path* with the OS default application (best effort)."""
    target = Path(path)
    try:
        if _is_windows():
            opener = getattr(os, "startfile", None)
            if opener is None:  # pragma: no cover - defensive
                return False
            opener(str(target))
        elif _is_macos():
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception:  # noqa: BLE001 - opening is a convenience, never fatal
        return False


def reveal_path(path: str | Path) -> bool:
    """Reveal *path* in the OS file manager (parent folder on Linux)."""
    target = Path(path)
    try:
        if _is_windows():
            subprocess.Popen(["explorer", "/select,", str(target)])
        elif _is_macos():
            subprocess.Popen(["open", "-R", str(target)])
        else:
            folder = target if target.is_dir() else target.parent
            subprocess.Popen(["xdg-open", str(folder)])
        return True
    except Exception:  # noqa: BLE001
        return False
