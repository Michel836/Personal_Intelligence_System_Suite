"""Portable volume identity resolution for scan-scoped lifecycle.

The lifecycle must be able to answer, for a scanned root:

* which *stable volume* it belongs to (so the same disk remounted elsewhere is
  recognised);
* whether that volume is currently mounted/available (so a disconnected disk
  can never be mistaken for deleted files).

Linux is the primary target; the resolver degrades gracefully elsewhere.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VolumeInfo:
    """Identity + availability of a volume for a scan scope."""

    stable_key: str
    device: Optional[str] = None
    fs_uuid: Optional[str] = None
    fs_type: Optional[str] = None
    mountpoint: str = "/"
    is_available: bool = True
    display_name: Optional[str] = None


def normalize_root(path: "str | Path") -> str:
    """Return a canonical absolute root path (symlinks resolved, no trailing /)."""
    resolved = os.path.realpath(os.fspath(path))
    if len(resolved) > 1:
        resolved = resolved.rstrip(os.sep) or os.sep
    return resolved


def _read_mountinfo() -> list[tuple[str, str, str, str]]:
    """Return ``(major:minor, mountpoint, fstype, source)`` tuples (Linux)."""
    entries: list[tuple[str, str, str, str]] = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 7 or "-" not in parts:
                    continue
                sep = parts.index("-")
                if sep + 2 >= len(parts):
                    continue
                entries.append((parts[2], parts[4], parts[sep + 1], parts[sep + 2]))
    except OSError:
        pass
    return entries


def _uuid_for_source(source: str) -> Optional[str]:
    """Resolve a filesystem UUID from ``/dev/disk/by-uuid`` if possible."""
    if not source:
        return None
    try:
        by_uuid = Path("/dev/disk/by-uuid")
        if not by_uuid.is_dir():
            return None
        target = os.path.realpath(source)
        for link in by_uuid.iterdir():
            try:
                if os.path.realpath(str(link)) == target:
                    return link.name
            except OSError:
                continue
    except OSError:
        pass
    return None


def _mount_for_device(device_number: str) -> Optional[tuple[str, str, str]]:
    """Return ``(mountpoint, fstype, source)`` for a major:minor device."""
    best: Optional[tuple[str, str, str]] = None
    for dev, mountpoint, fstype, source in _read_mountinfo():
        if dev != device_number:
            continue
        if best is None or len(mountpoint) > len(best[0]):
            best = (mountpoint, fstype, source)
    return best


def resolve_volume(path: "str | Path") -> VolumeInfo:
    """Resolve the stable volume identity for ``path``.

    ``stable_key`` prefers ``fsuuid:<uuid>`` (stable across remounts), then
    ``dev:<source device>``, then ``stdev:<device>``. Availability reflects
    whether the containing mount is currently mounted.
    """
    root = normalize_root(path)
    try:
        stat_result = os.stat(root)
        device = stat_result.st_dev
    except OSError:
        return VolumeInfo(stable_key=f"path:{root}", mountpoint=root, is_available=False)

    try:
        device_number = f"{os.major(device)}:{os.minor(device)}"
    except (AttributeError, ValueError, OverflowError):
        device_number = str(device)

    mount = _mount_for_device(device_number)
    if mount is None:
        return VolumeInfo(
            stable_key=f"stdev:{device}",
            device=device_number,
            mountpoint=root,
            is_available=os.path.isdir(root),
        )

    mountpoint, fs_type, source = mount
    fs_uuid = _uuid_for_source(source)
    if fs_uuid:
        stable_key = f"fsuuid:{fs_uuid}"
    elif source:
        stable_key = f"dev:{source}"
    else:
        stable_key = f"stdev:{device}"

    return VolumeInfo(
        stable_key=stable_key,
        device=source or device_number,
        fs_uuid=fs_uuid,
        fs_type=fs_type,
        mountpoint=mountpoint,
        is_available=os.path.ismount(mountpoint),
        display_name=mountpoint,
    )


def roots_overlap(first: str, second: str) -> bool:
    """True when two roots are equal or one contains the other."""
    a = normalize_root(first)
    b = normalize_root(second)
    if a == b:
        return True
    a_prefix = a.rstrip(os.sep) + os.sep
    b_prefix = b.rstrip(os.sep) + os.sep
    return a.startswith(b_prefix) or b.startswith(a_prefix)
