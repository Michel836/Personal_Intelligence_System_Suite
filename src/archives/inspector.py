"""Canonical, safety-hardened archive inspection abstraction (M009J.5-.14).

Only *listing* and *bounded member reads* are performed. Member paths are
sanitized and can never escape the virtual archive namespace; symlinks,
hardlinks and device entries are surfaced as metadata-only virtual members and
are never followed. No member is ever written into a source directory.
"""

from __future__ import annotations

import bz2
import gzip
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO, Dict, List, Optional, Tuple

from loguru import logger

from .limits import ArchiveLimits

# --- formats ---------------------------------------------------------------

_EXT_FORMATS: Dict[str, str] = {
    ".tar.gz": "TAR_GZ",
    ".tar.bz2": "TAR_BZ2",
    ".tar.xz": "TAR_XZ",
    ".tgz": "TAR_GZ",
    ".tbz2": "TAR_BZ2",
    ".txz": "TAR_XZ",
    ".tar": "TAR",
    ".zip": "ZIP",
    ".7z": "SEVENZIP",
    ".rar": "RAR",
    ".gz": "GZ",
    ".bz2": "BZ2",
    ".xz": "XZ",
}

_MAGIC_ZIP = b"PK\x03\x04"
_MAGIC_7Z = b"7z\xbc\xaf\x27\x1c"
_MAGIC_RAR = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")


class ArchiveFormat(str, Enum):
    ZIP = "ZIP"
    TAR = "TAR"
    TAR_GZ = "TAR_GZ"
    TAR_BZ2 = "TAR_BZ2"
    TAR_XZ = "TAR_XZ"
    GZ = "GZ"
    BZ2 = "BZ2"
    XZ = "XZ"
    SEVENZIP = "SEVENZIP"
    RAR = "RAR"
    UNKNOWN = "UNKNOWN"

    @property
    def is_container(self) -> bool:
        return self is not ArchiveFormat.UNKNOWN

    @property
    def is_tar(self) -> bool:
        return self in {
            ArchiveFormat.TAR,
            ArchiveFormat.TAR_GZ,
            ArchiveFormat.TAR_BZ2,
            ArchiveFormat.TAR_XZ,
        }

    @property
    def is_bare_stream(self) -> bool:
        return self in {ArchiveFormat.GZ, ArchiveFormat.BZ2, ArchiveFormat.XZ}


ARCHIVE_FORMATS = frozenset(_EXT_FORMATS)


class MemberType(str, Enum):
    FILE = "FILE"
    DIR = "DIR"
    SYMLINK = "SYMLINK"
    HARDLINK = "HARDLINK"
    DEVICE = "DEVICE"
    FIFO = "FIFO"
    OTHER = "OTHER"


class ArchiveStatus(str, Enum):
    OK = "OK"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    CORRUPT_ARCHIVE = "CORRUPT_ARCHIVE"
    PASSWORD_REQUIRED = "PASSWORD_REQUIRED"
    TIMEOUT = "TIMEOUT"
    LIMIT_DEPTH = "LIMIT_DEPTH"
    LIMIT_MEMBER_COUNT = "LIMIT_MEMBER_COUNT"
    LIMIT_MEMBER_SIZE = "LIMIT_MEMBER_SIZE"
    LIMIT_TOTAL_SIZE = "LIMIT_TOTAL_SIZE"
    LIMIT_COMPRESSION_RATIO = "LIMIT_COMPRESSION_RATIO"
    DISABLED = "DISABLED"


class ArchiveLimitError(Exception):
    """Raised internally when a hard limit is hit; carries a status."""

    def __init__(self, status: ArchiveStatus, message: str = ""):
        super().__init__(message or status.value)
        self.status = status


@dataclass(frozen=True)
class ArchiveMember:
    """A member inside an archive (never a real filesystem path)."""

    member_path: str
    raw_name: str
    member_type: MemberType = MemberType.FILE
    uncompressed_size: int = 0
    compressed_size: int = 0
    crc: Optional[str] = None
    is_encrypted: bool = False
    modified_at: Optional[str] = None

    @property
    def is_file(self) -> bool:
        return self.member_type is MemberType.FILE

    @property
    def ratio(self) -> float:
        if self.compressed_size <= 0:
            return 0.0
        return self.uncompressed_size / self.compressed_size


@dataclass
class ArchiveBudget:
    """Mutable cumulative budget shared by nested archives (M009J.14)."""

    bytes_seen: int = 0
    members_seen: int = 0


# --- detection / helpers ---------------------------------------------------


def _suffix_format(name: str) -> Optional[ArchiveFormat]:
    lowered = name.lower()
    for suffix, fmt in _EXT_FORMATS.items():
        if lowered.endswith(suffix):
            return ArchiveFormat(fmt)
    return None


def detect_format(path: Path | str, *, magic: bool = True) -> ArchiveFormat:
    """Detect archive format by extension, corroborated by magic bytes."""
    by_ext = _suffix_format(str(path))
    if not magic:
        return by_ext or ArchiveFormat.UNKNOWN
    try:
        with open(str(path), "rb") as fh:
            head = fh.read(8)
    except OSError:
        return by_ext or ArchiveFormat.UNKNOWN
    if head.startswith(_MAGIC_ZIP):
        return ArchiveFormat.ZIP
    if head.startswith(_MAGIC_7Z):
        return ArchiveFormat.SEVENZIP
    if head.startswith(_MAGIC_RAR):
        return ArchiveFormat.RAR
    if head.startswith(b"\x1f\x8b"):
        return by_ext if by_ext and by_ext.is_tar else ArchiveFormat.GZ
    if head.startswith(b"BZh"):
        return by_ext if by_ext and by_ext.is_tar else ArchiveFormat.BZ2
    if head.startswith(b"\xfd7zXZ\x00"):
        return by_ext if by_ext and by_ext.is_tar else ArchiveFormat.XZ
    return by_ext or ArchiveFormat.UNKNOWN


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def sanitize_member_path(name: str) -> Optional[str]:
    """Return a safe relative POSIX member path, or ``None`` if unsafe.

    Rejects NUL bytes, absolute POSIX paths, UNC paths, Windows drive and
    drive-relative paths, and any parent traversal. The result can never escape
    the virtual archive namespace.
    """
    if not name or "\x00" in name:
        return None
    candidate = name.replace("\\", "/")
    if candidate.startswith("/") or candidate.startswith("//"):
        return None
    if _DRIVE_RE.match(candidate):
        return None
    parts: List[str] = []
    for part in candidate.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    joined = "/".join(parts)
    if not joined.strip():
        return None
    return joined


def virtual_path(parent_path: str, member_path: str) -> str:
    """Stable, unambiguous display/search identity for an archive member."""
    return f"{parent_path}!/{member_path}"


def _norm_crc(value) -> Optional[str]:
    if value in (None, 0, "", "-"):
        return None
    try:
        return f"{int(str(value), 16) & 0xFFFFFFFF:08x}"
    except (TypeError, ValueError):
        return None


def _dt(tup) -> Optional[str]:
    try:
        import datetime

        return datetime.datetime(*tup).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _lzma_available() -> bool:
    try:
        import lzma  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _sevenzip_binary() -> Optional[str]:
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _rar_backend_available() -> bool:
    try:
        import rarfile
    except ImportError:
        return False
    for tool in ("UNRAR_TOOL", "UNAR_TOOL", "BSDTAR_TOOL", "SEVENZIP_TOOL"):
        candidate = getattr(rarfile, tool, None)
        if candidate and shutil.which(candidate):
            return True
    return False


# --- inspector -------------------------------------------------------------


class ArchiveInspector:
    """Inspect a single archive level (recursion handled by the indexer)."""

    def __init__(
        self,
        path: Path | str,
        *,
        limits: Optional[ArchiveLimits] = None,
        budget: Optional[ArchiveBudget] = None,
        depth: int = 0,
        format_hint: Optional[ArchiveFormat] = None,
    ):
        self.path = Path(path)
        self.limits = limits or ArchiveLimits.from_env()
        self.budget = budget if budget is not None else ArchiveBudget()
        self.depth = depth
        self.format = format_hint or detect_format(self.path)

    # -- metadata ----------------------------------------------------------
    def fingerprint(self, *, full_hash_limit: int = 0) -> str:
        """Parent fingerprint (size + mtime, optional bounded content hash)."""
        import hashlib

        try:
            st = self.path.stat()
        except OSError:
            return ""
        parts = [str(st.st_size), str(int(st.st_mtime))]
        if full_hash_limit > 0:
            h = hashlib.sha1()
            remaining = full_hash_limit
            try:
                with open(self.path, "rb") as fh:
                    while remaining > 0:
                        chunk = fh.read(min(65536, remaining))
                        if not chunk:
                            break
                        h.update(chunk)
                        remaining -= len(chunk)
            except OSError:
                return ""
            parts.append(h.hexdigest())
        return ":".join(parts)

    # -- listing -----------------------------------------------------------
    def list_members(self) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        """Return sanitized members plus a status; never raises."""
        if self.depth > self.limits.max_depth:
            return [], ArchiveStatus.LIMIT_DEPTH
        if not self.format.is_container:
            return [], ArchiveStatus.UNSUPPORTED_FORMAT
        deadline = time.monotonic() + self.limits.timeout
        try:
            if self.format is ArchiveFormat.ZIP:
                return self._list_zip(deadline)
            if self.format.is_tar:
                return self._list_tar(deadline)
            if self.format is ArchiveFormat.SEVENZIP:
                return self._list_7z(deadline)
            if self.format is ArchiveFormat.RAR:
                return self._list_rar(deadline)
            if self.format.is_bare_stream:
                return self._list_bare()
        except ArchiveLimitError as exc:
            return [], exc.status
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"archive list failed for {self.path}: {exc}")
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        return [], ArchiveStatus.UNSUPPORTED_FORMAT

    def _check_member(self, size: int, compressed: int, deadline: float) -> None:
        if time.monotonic() > deadline:
            raise ArchiveLimitError(ArchiveStatus.TIMEOUT)
        if size > self.limits.max_member_bytes:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
        self.budget.bytes_seen += max(size, 0)
        self.budget.members_seen += 1
        if self.budget.members_seen > self.limits.max_members:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_COUNT)
        if self.budget.bytes_seen > self.limits.max_total_uncompressed:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_TOTAL_SIZE)
        if compressed > 0 and size > 1024 * 1024 and size / compressed > self.limits.max_ratio:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_COMPRESSION_RATIO)

    def _list_zip(self, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        members: List[ArchiveMember] = []
        try:
            zf = zipfile.ZipFile(self.path, "r")
        except zipfile.BadZipFile:
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        with zf:
            for info in zf.infolist():
                safe = sanitize_member_path(info.filename)
                if safe is None:
                    logger.warning(f"skipping unsafe archive member in {self.path.name}")
                    continue
                is_dir = info.is_dir() or info.filename.endswith("/")
                size = 0 if is_dir else int(info.file_size)
                compressed = 0 if is_dir else int(info.compress_size)
                try:
                    self._check_member(size, compressed, deadline)
                except ArchiveLimitError as exc:
                    return members, exc.status
                members.append(
                    ArchiveMember(
                        member_path=safe,
                        raw_name=info.filename,
                        member_type=MemberType.DIR if is_dir else MemberType.FILE,
                        uncompressed_size=size,
                        compressed_size=compressed,
                        crc=_norm_crc(info.CRC),
                        is_encrypted=bool(info.flag_bits & 0x1),
                        modified_at=_dt((info.date_time + (0, 0, 0))[:6]),
                    )
                )
            files = [m for m in members if m.is_file]
            if files and all(m.is_encrypted for m in files):
                return members, ArchiveStatus.PASSWORD_REQUIRED
        return members, ArchiveStatus.OK

    def _tar_handle(self) -> Tuple[Optional[tarfile.TarFile], Optional[tempfile.TemporaryDirectory]]:
        """Open a tar, transparently decompressing .xz via the 7z CLI if needed."""
        if self.format is ArchiveFormat.TAR_XZ and not _lzma_available():
            tmpdir = tempfile.TemporaryDirectory(prefix="pis-arc-")
            inner = os.path.join(tmpdir.name, "inner.tar")
            if not self._cli_extract_stream(inner):
                tmpdir.cleanup()
                raise ArchiveLimitError(ArchiveStatus.BACKEND_UNAVAILABLE)
            return tarfile.open(inner, "r:"), tmpdir
        mode = {
            ArchiveFormat.TAR: "r:",
            ArchiveFormat.TAR_GZ: "r:gz",
            ArchiveFormat.TAR_BZ2: "r:bz2",
            ArchiveFormat.TAR_XZ: "r:xz",
        }[self.format]
        return tarfile.open(self.path, mode), None

    def _list_tar(self, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        members: List[ArchiveMember] = []
        try:
            tf, tmpdir = self._tar_handle()
        except ArchiveLimitError as exc:
            return [], exc.status
        except (tarfile.TarError, EOFError, OSError):
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        try:
            with tf:
                for info in tf.getmembers():
                    safe = sanitize_member_path(info.name)
                    if safe is None:
                        logger.warning(f"skipping unsafe archive member in {self.path.name}")
                        continue
                    if info.isfile():
                        mtype, size = MemberType.FILE, int(info.size)
                    elif info.isdir():
                        mtype, size = MemberType.DIR, 0
                    elif info.issym():
                        mtype, size = MemberType.SYMLINK, 0
                    elif info.islnk():
                        mtype, size = MemberType.HARDLINK, 0
                    elif info.ischr() or info.isblk():
                        mtype, size = MemberType.DEVICE, 0
                    elif info.isfifo():
                        mtype, size = MemberType.FIFO, 0
                    else:
                        mtype, size = MemberType.OTHER, 0
                    try:
                        self._check_member(size, 0, deadline)
                    except ArchiveLimitError as exc:
                        return members, exc.status
                    members.append(
                        ArchiveMember(
                            member_path=safe,
                            raw_name=info.name,
                            member_type=mtype,
                            uncompressed_size=size,
                            compressed_size=0,
                            crc=None,
                            is_encrypted=False,
                            modified_at=str(info.mtime) if info.mtime else None,
                        )
                    )
        finally:
            if tmpdir is not None:
                tmpdir.cleanup()
        return members, ArchiveStatus.OK

    def _list_7z(self, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        if _lzma_available():
            try:
                import py7zr

                return self._list_7z_py7zr(py7zr, deadline)
            except ImportError:
                pass
        return self._list_7z_cli(deadline)

    def _list_7z_py7zr(self, py7zr, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        members: List[ArchiveMember] = []
        try:
            with py7zr.SevenZipFile(self.path, "r") as archive:
                encrypted = bool(getattr(archive, "needs_password", False))
                for info in archive.list():
                    safe = sanitize_member_path(info.filename)
                    if safe is None:
                        continue
                    is_dir = bool(getattr(info, "is_directory", False))
                    size = 0 if is_dir else int(getattr(info, "uncompressed", 0) or 0)
                    compressed = 0 if is_dir else int(getattr(info, "compressed", 0) or 0)
                    try:
                        self._check_member(size, compressed, deadline)
                    except ArchiveLimitError as exc:
                        return members, exc.status
                    members.append(
                        ArchiveMember(
                            member_path=safe,
                            raw_name=info.filename,
                            member_type=MemberType.DIR if is_dir else MemberType.FILE,
                            uncompressed_size=size,
                            compressed_size=compressed,
                            crc=_norm_crc(getattr(info, "crc32", None)),
                            is_encrypted=encrypted,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            if "password" in str(exc).lower():
                return [], ArchiveStatus.PASSWORD_REQUIRED
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        return members, ArchiveStatus.OK

    def _list_7z_cli(self, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        binary = _sevenzip_binary()
        if not binary:
            return [], ArchiveStatus.BACKEND_UNAVAILABLE
        try:
            proc = subprocess.run(
                [binary, "l", "-slt", "-p-", "--", str(self.path)],
                capture_output=True, text=True, errors="replace", timeout=self.limits.timeout,
            )
        except subprocess.TimeoutExpired:
            return [], ArchiveStatus.TIMEOUT
        if "Cannot open" in proc.stdout or "is not archive" in proc.stdout:
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        records = self._parse_7z_slt(proc.stdout)
        if records is None:
            # password-protected archives can still list, but headers may fail
            if "Wrong password" in proc.stdout or "Enter password" in proc.stdout:
                return [], ArchiveStatus.PASSWORD_REQUIRED
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        members: List[ArchiveMember] = []
        for rec in records:
            safe = sanitize_member_path(rec.get("Path", ""))
            if safe is None:
                continue
            attrs = rec.get("Attributes", "")
            is_dir = attrs.startswith("D") or rec.get("Folder") == "+"
            encrypted = rec.get("Encrypted") == "+"
            size = 0 if is_dir else int(rec.get("Size") or 0)
            compressed = int(rec.get("Packed Size") or 0)
            try:
                self._check_member(size, compressed, deadline)
            except ArchiveLimitError as exc:
                return members, exc.status
            members.append(
                ArchiveMember(
                    member_path=safe,
                    raw_name=rec.get("Path", ""),
                    member_type=MemberType.DIR if is_dir else MemberType.FILE,
                    uncompressed_size=size,
                    compressed_size=compressed,
                    crc=_norm_crc(rec.get("CRC")),
                    is_encrypted=encrypted,
                    modified_at=rec.get("Modified"),
                )
            )
        files = [m for m in members if m.is_file]
        if files and all(m.is_encrypted for m in files):
            # 7z marks empty-password (headered) archives as encrypted; only a
            # real password test distinguishes a locked archive from a plain one.
            if self._sevenzip_needs_password(binary):
                return members, ArchiveStatus.PASSWORD_REQUIRED
        return members, ArchiveStatus.OK

    def _sevenzip_needs_password(self, binary: str) -> bool:
        try:
            proc = subprocess.run(
                [binary, "t", "-p-", "--", str(self.path)],
                capture_output=True, text=True, errors="replace", timeout=self.limits.timeout,
            )
        except subprocess.TimeoutExpired:
            return True
        text = (proc.stdout + proc.stderr).lower()
        if "wrong password" in text or "enter password" in text or "cannot open encrypted" in text:
            return True
        return False

    @staticmethod
    def _parse_7z_slt(text: str) -> Optional[List[Dict[str, str]]]:
        """Parse ``7z l -slt`` member records (after the dashed separator)."""
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if set(line.strip()) == {"-"} and len(line.strip()) >= 5:
                start = i + 1
                break
        if start is None:
            return None
        records: List[Dict[str, str]] = []
        current: Dict[str, str] = {}
        for line in lines[start:]:
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            if " = " in line:
                key, _, value = line.partition(" = ")
                current[key.strip()] = value.strip()
        if current:
            records.append(current)
        # Drop the archive-level record (no Path or Path == archive name).
        return [r for r in records if r.get("Path")]

    def _list_rar(self, deadline: float) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        try:
            import rarfile
        except ImportError:
            return [], ArchiveStatus.BACKEND_UNAVAILABLE
        if not _rar_backend_available():
            return [], ArchiveStatus.BACKEND_UNAVAILABLE
        members: List[ArchiveMember] = []
        try:
            with rarfile.RarFile(self.path) as rf:
                encrypted = False
                try:
                    encrypted = bool(rf.needs_password())
                except Exception:  # noqa: BLE001
                    pass
                for info in rf.infolist():
                    safe = sanitize_member_path(info.filename)
                    if safe is None:
                        continue
                    is_dir = info.isdir()
                    size = 0 if is_dir else int(info.file_size)
                    compressed = 0 if is_dir else int(info.compress_size)
                    try:
                        self._check_member(size, compressed, deadline)
                    except ArchiveLimitError as exc:
                        return members, exc.status
                    try:
                        enc = bool(info.needs_password())
                    except Exception:  # noqa: BLE001
                        enc = encrypted
                    members.append(
                        ArchiveMember(
                            member_path=safe,
                            raw_name=info.filename,
                            member_type=MemberType.DIR if is_dir else MemberType.FILE,
                            uncompressed_size=size,
                            compressed_size=compressed,
                            crc=_norm_crc(info.CRC),
                            is_encrypted=enc or encrypted,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "password" in text or "encrypted" in text:
                return [], ArchiveStatus.PASSWORD_REQUIRED
            return [], ArchiveStatus.CORRUPT_ARCHIVE
        files = [m for m in members if m.is_file]
        if files and all(m.is_encrypted for m in files):
            return members, ArchiveStatus.PASSWORD_REQUIRED
        return members, ArchiveStatus.OK

    def _list_bare(self) -> Tuple[List[ArchiveMember], ArchiveStatus]:
        name = self.path.name
        for suffix in (".gz", ".bz2", ".xz"):
            if name.lower().endswith(suffix):
                name = name[: -len(suffix)]
                break
        if not name:
            name = "content"
        return [ArchiveMember(member_path=name, raw_name=name, member_type=MemberType.FILE)], ArchiveStatus.OK

    # -- bounded reads -----------------------------------------------------
    def open_member(self, member: ArchiveMember) -> io.BytesIO:
        """Return a bounded, in-memory reader for a regular file member."""
        if member.member_type is not MemberType.FILE:
            raise ArchiveLimitError(ArchiveStatus.UNSUPPORTED_FORMAT, "not a regular file")
        if member.uncompressed_size > self.limits.max_member_bytes:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
        deadline = time.monotonic() + self.limits.timeout
        try:
            if self.format is ArchiveFormat.ZIP:
                return self._open_zip(member, deadline)
            if self.format.is_tar:
                return self._open_tar(member, deadline)
            if self.format is ArchiveFormat.SEVENZIP:
                return self._open_7z(member, deadline)
            if self.format is ArchiveFormat.RAR:
                return self._open_rar(member, deadline)
            if self.format.is_bare_stream:
                return self._open_bare(deadline)
        except ArchiveLimitError:
            raise
        except zipfile.BadZipFile:
            raise ArchiveLimitError(ArchiveStatus.CORRUPT_ARCHIVE)
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "password" in text or "encrypted" in text:
                raise ArchiveLimitError(ArchiveStatus.PASSWORD_REQUIRED)
            raise ArchiveLimitError(ArchiveStatus.CORRUPT_ARCHIVE)
        raise ArchiveLimitError(ArchiveStatus.UNSUPPORTED_FORMAT)

    def _read_bounded(self, fp: IO[bytes], deadline: float) -> io.BytesIO:
        buf = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise ArchiveLimitError(ArchiveStatus.TIMEOUT)
            chunk = fp.read(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > self.limits.max_member_bytes:
                raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
        self.budget.bytes_seen += len(buf)
        if self.budget.bytes_seen > self.limits.max_total_uncompressed:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_TOTAL_SIZE)
        return io.BytesIO(bytes(buf))

    def _open_zip(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        with zipfile.ZipFile(self.path, "r") as zf:
            info = zf.getinfo(member.raw_name)
            if info.flag_bits & 0x1:
                raise ArchiveLimitError(ArchiveStatus.PASSWORD_REQUIRED)
            with zf.open(info, "r") as fp:
                return self._read_bounded(fp, deadline)

    def _open_tar(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        tf, tmpdir = self._tar_handle()
        try:
            with tf:
                info = tf.getmember(member.raw_name)
                if not info.isfile():
                    raise ArchiveLimitError(ArchiveStatus.UNSUPPORTED_FORMAT)
                fp = tf.extractfile(info)
                if fp is None:
                    raise ArchiveLimitError(ArchiveStatus.CORRUPT_ARCHIVE)
                with fp:
                    return self._read_bounded(fp, deadline)
        finally:
            if tmpdir is not None:
                tmpdir.cleanup()

    def _open_7z(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        if _lzma_available():
            try:
                return self._open_7z_py7zr(member, deadline)
            except ImportError:
                pass
        return self._cli_open_member(member, deadline)

    def _open_7z_py7zr(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        import py7zr

        with py7zr.SevenZipFile(self.path, "r") as archive:
            if bool(getattr(archive, "needs_password", False)):
                raise ArchiveLimitError(ArchiveStatus.PASSWORD_REQUIRED)
            if time.monotonic() > deadline:
                raise ArchiveLimitError(ArchiveStatus.TIMEOUT)
            data = archive.read(targets=[member.raw_name])
        if not data:
            raise ArchiveLimitError(ArchiveStatus.CORRUPT_ARCHIVE)
        payload = next(iter(data.values())).read()
        if len(payload) > self.limits.max_member_bytes:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
        self.budget.bytes_seen += len(payload)
        if self.budget.bytes_seen > self.limits.max_total_uncompressed:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_TOTAL_SIZE)
        return io.BytesIO(payload)

    def _open_rar(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        import rarfile

        with rarfile.RarFile(self.path) as rf:
            info = rf.getinfo(member.raw_name)
            if info.needs_password():
                raise ArchiveLimitError(ArchiveStatus.PASSWORD_REQUIRED)
            with rf.open(info) as fp:
                return self._read_bounded(fp, deadline)

    def _open_bare(self, deadline: float) -> io.BytesIO:
        if self.format is ArchiveFormat.GZ:
            with gzip.open(self.path, "rb") as fp:
                return self._read_bounded(fp, deadline)
        if self.format is ArchiveFormat.BZ2:
            with bz2.open(self.path, "rb") as fp:
                return self._read_bounded(fp, deadline)
        if self.format is ArchiveFormat.XZ and _lzma_available():
            import lzma

            with lzma.open(self.path, "rb") as fp:
                return self._read_bounded(fp, deadline)
        buf = self._cli_read_stream(deadline)
        return buf

    # -- 7z CLI streaming (no filesystem writes except an explicit temp) ----
    def _cli_read_stream(self, deadline: float) -> io.BytesIO:
        binary = _sevenzip_binary()
        if not binary:
            raise ArchiveLimitError(ArchiveStatus.BACKEND_UNAVAILABLE)
        proc = subprocess.Popen(
            [binary, "x", "-so", "-y", "-p-", "--", str(self.path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            return self._read_process_bounded(proc, deadline)
        finally:
            _terminate(proc)

    def _cli_open_member(self, member: ArchiveMember, deadline: float) -> io.BytesIO:
        binary = _sevenzip_binary()
        if not binary:
            raise ArchiveLimitError(ArchiveStatus.BACKEND_UNAVAILABLE)
        proc = subprocess.Popen(
            [binary, "x", "-so", "-y", "-p-", "--", str(self.path), member.raw_name],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            return self._read_process_bounded(proc, deadline)
        finally:
            _terminate(proc)

    def _read_process_bounded(self, proc: subprocess.Popen, deadline: float) -> io.BytesIO:
        assert proc.stdout is not None
        os.set_blocking(proc.stdout.fileno(), False)
        buf = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise ArchiveLimitError(ArchiveStatus.TIMEOUT)
            chunk = proc.stdout.read(65536)
            if chunk:
                buf.extend(chunk)
                if len(buf) > self.limits.max_member_bytes:
                    raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
                continue
            if proc.poll() is not None:
                remainder = proc.stdout.read() or b""
                buf.extend(remainder)
                break
            if len(buf) > self.limits.max_member_bytes:
                raise ArchiveLimitError(ArchiveStatus.LIMIT_MEMBER_SIZE)
            time.sleep(0.01)
        self.budget.bytes_seen += len(buf)
        if self.budget.bytes_seen > self.limits.max_total_uncompressed:
            raise ArchiveLimitError(ArchiveStatus.LIMIT_TOTAL_SIZE)
        return io.BytesIO(bytes(buf))

    def _cli_extract_stream(self, dest: str) -> bool:
        """Write the decompressed outer stream into ``dest`` (bounded)."""
        binary = _sevenzip_binary()
        if not binary:
            return False
        deadline = time.monotonic() + self.limits.timeout
        proc = subprocess.Popen(
            [binary, "x", "-so", "-y", "-p-", "--", str(self.path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        total = 0
        try:
            with open(dest, "wb") as out:
                assert proc.stdout is not None
                os.set_blocking(proc.stdout.fileno(), False)
                while True:
                    if time.monotonic() > deadline:
                        return False
                    chunk = proc.stdout.read(65536)
                    if chunk:
                        total += len(chunk)
                        if total > self.limits.max_total_uncompressed:
                            return False
                        out.write(chunk)
                        continue
                    if proc.poll() is not None:
                        out.write(proc.stdout.read() or b"")
                        break
                    time.sleep(0.01)
        finally:
            _terminate(proc)
        return True


def _terminate(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def _call_flag(obj, name: str) -> bool:
    try:
        attr = getattr(obj, name)
        return bool(attr() if callable(attr) else attr)
    except Exception:  # noqa: BLE001
        return False
