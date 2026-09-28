"""Disk utilities for drive detection and selection."""

import os
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List


def get_available_drives() -> List[Dict[str, Any]]:
    """Return user-meaningful mounted volumes, not every kernel mount.

    On Linux ``/proc/mounts`` contains pseudo filesystems, bind mounts, sandbox
    mounts and application mounts.  Those are not disks and must not inflate the
    UI's drive count.  Physical/local volumes are deduplicated by ``st_dev`` so
    one filesystem exposed at several mount points is shown once.
    """
    drives: List[Dict[str, Any]] = []

    if platform.system() == "Windows":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_path = f"{letter}:\\\\"
            if not os.path.exists(drive_path):
                continue
            try:
                total, used, free = shutil.disk_usage(drive_path)
            except OSError:
                continue
            drive_type = _get_drive_type_windows(letter)
            label = _get_drive_label_windows(letter)
            drives.append({
                "letter": letter,
                "path": drive_path,
                "label": label,
                "type": drive_type,
                "total_space": total,
                "used_space": used,
                "free_space": free,
                "usage_percent": (used / total) * 100 if total else 0,
                "display_name": f"{letter}: ({_format_size(total)}) - {label or 'Local Disk'}",
            })
    else:
        drives = _get_unix_drives()

    return sorted(drives, key=lambda item: item.get("letter", item["path"]))


def _get_drive_type_windows(letter: str) -> str:
    import ctypes

    try:
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\\\")
        return {
            0: "unknown",
            1: "invalid",
            2: "removable",
            3: "fixed",
            4: "remote",
            5: "cdrom",
            6: "ramdisk",
        }.get(drive_type, "unknown")
    except Exception:
        return "unknown"


def _get_drive_label_windows(letter: str) -> str:
    import ctypes

    try:
        drive_path = f"{letter}:\\\\"
        volume_name = ctypes.create_unicode_buffer(1024)
        fs_name = ctypes.create_unicode_buffer(1024)
        result = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_path),
            volume_name,
            ctypes.sizeof(volume_name),
            None,
            None,
            None,
            fs_name,
            ctypes.sizeof(fs_name),
        )
        return volume_name.value if result else ""
    except Exception:
        return ""


def _decode_mount_field(value: str) -> str:
    """Decode the escaping used by /proc/mounts."""
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _is_user_volume_source(device: str, fs_type: str, mount_point: str) -> bool:
    """Return whether a mount represents a selectable storage volume."""
    # Real Linux block devices, including LUKS/LVM/device-mapper volumes.
    if device.startswith("/dev/"):
        return True

    # Common network-volume sources.  They are legitimate selectable volumes,
    # but remain classified separately from local fixed disks.
    if device.startswith("//") or fs_type in {"cifs", "smb3", "nfs", "nfs4"}:
        return True

    # Everything else in /proc/mounts (proc, sysfs, tmpfs, overlay, portal,
    # squashfs, gvfs, Flatpak/Snap helper mounts, etc.) is not a physical disk.
    return False


def _get_unix_drives() -> List[Dict[str, Any]]:
    """Return mounted storage volumes on Linux/Unix without pseudo mounts."""
    drives: List[Dict[str, Any]] = []
    seen_local_devices: set[int] = set()
    seen_remote: set[tuple[str, str]] = set()

    try:
        with open("/proc/mounts", "r", encoding="utf-8") as mounts:
            rows = list(mounts)
    except OSError:
        rows = []

    for line in rows:
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        raw_device, raw_mount, fs_type = parts[:3]
        device = _decode_mount_field(raw_device)
        mount_point = _decode_mount_field(raw_mount)

        if not _is_user_volume_source(device, fs_type, mount_point):
            continue
        if not os.path.isdir(mount_point):
            continue

        try:
            stat_result = os.stat(mount_point)
            total, used, free = shutil.disk_usage(mount_point)
        except OSError:
            continue

        is_remote = device.startswith("//") or fs_type in {"cifs", "smb3", "nfs", "nfs4"}
        if is_remote:
            remote_key = (device, mount_point)
            if remote_key in seen_remote:
                continue
            seen_remote.add(remote_key)
            drive_type = "remote"
        else:
            # st_dev identifies the mounted filesystem.  Bind mounts and other
            # aliases of the same filesystem must not appear as extra disks.
            device_id = int(stat_result.st_dev)
            if device_id in seen_local_devices:
                continue
            seen_local_devices.add(device_id)
            drive_type = (
                "removable"
                if mount_point.startswith(("/media/", "/run/media/"))
                else "fixed"
            )

        label = os.path.basename(mount_point.rstrip("/")) or device
        drives.append({
            "device": device,
            "path": mount_point,
            "label": label,
            "type": drive_type,
            "fs_type": fs_type,
            "total_space": total,
            "used_space": used,
            "free_space": free,
            "usage_percent": (used / total) * 100 if total else 0,
            "display_name": f"{mount_point} ({_format_size(total)}) - {device}",
        })

    if not drives:
        try:
            total, used, free = shutil.disk_usage("/")
            drives.append({
                "device": "/",
                "path": "/",
                "label": "Root",
                "type": "fixed",
                "total_space": total,
                "used_space": used,
                "free_space": free,
                "usage_percent": (used / total) * 100 if total else 0,
                "display_name": f"/ ({_format_size(total)}) - Root",
            })
        except OSError:
            pass

    return drives


def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    names = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    size = float(size_bytes)
    while size >= 1024.0 and index < len(names) - 1:
        size /= 1024.0
        index += 1
    return f"{size:.1f} {names[index]}"


def get_recommended_drives() -> List[str]:
    """Return sensible default volumes for scanning."""
    recommended: List[str] = []
    for drive in get_available_drives():
        if drive["usage_percent"] > 95:
            continue
        if drive["total_space"] < 1024**3:
            continue
        if drive.get("type") in {"cdrom", "ramdisk", "remote"}:
            continue
        recommended.append(drive["path"])
    return recommended


def validate_scan_path(path: str) -> Dict[str, Any]:
    """Validate a scan path without inventing a misleading file-count estimate."""
    result: Dict[str, Any] = {
        "valid": False,
        "accessible": False,
        "writable": False,
        "estimated_files": 0,
        "warnings": [],
        "errors": [],
    }

    try:
        path_obj = Path(path)
        if not path_obj.exists():
            result["errors"].append(f"Path does not exist: {path}")
            return result
        if not path_obj.is_dir():
            result["errors"].append(f"Path is not a directory: {path}")
            return result

        result["accessible"] = os.access(path, os.R_OK | os.X_OK)
        if not result["accessible"]:
            result["errors"].append(f"Path not readable/traversable: {path}")
            return result

        # Scanning is read-only.  Lack of write permission on the source volume
        # is not a limitation because the SQLite DB lives elsewhere.
        result["writable"] = os.access(path, os.W_OK)
        result["valid"] = True

        # A 10-directory sample produced spectacularly wrong estimates on real
        # Linux roots (e.g. ~2,028 vs >1.5M files).  Until a bounded estimator is
        # statistically defensible, report no estimate rather than false data.
        result["estimated_files"] = 0
    except Exception as exc:
        result["errors"].append(f"Path validation error: {exc}")

    return result
