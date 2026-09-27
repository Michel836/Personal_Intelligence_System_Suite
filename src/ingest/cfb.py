"""Minimal bounded OLE Compound File (CFB) reader for MSG metadata (M017).

Stdlib-only, read-only, bounded by stream count and total bytes. Extracts only
the ``__substg1.0_*`` property streams used by Outlook ``.msg`` files. Never
writes to the source and never executes attachments.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_DIFSECT = 0xFFFFFFFC


class CfbError(Exception):
    pass


def _u32(buf: bytes, off: int) -> int:
    return int(struct.unpack_from("<I", buf, off)[0])


def _u16(buf: bytes, off: int) -> int:
    return int(struct.unpack_from("<H", buf, off)[0])


def _chain(_buf: bytes, fat: list[int], start: int, _sector_size: int, max_sectors: int) -> list[int]:
    out: list[int] = []
    sector = start
    seen: set[int] = set()
    while sector not in (_ENDOFCHAIN, _FREESECT, _FATSECT, _DIFSECT) and sector < len(fat):
        if sector in seen or len(out) >= max_sectors:
            break
        seen.add(sector)
        out.append(sector)
        sector = fat[sector]
    return out


def _read_sectors(buf: bytes, fat: list[int], start: int, sector_size: int) -> bytes:
    chunks: list[bytes] = []
    for s in _chain(buf, fat, start, sector_size, len(fat) + 1):
        off = (s + 1) * sector_size
        chunks.append(buf[off:off + sector_size])
    return b"".join(chunks)


def read_cfb_streams(path: Path | str, *, max_streams: int = 512,
                     max_total_bytes: int = 8 * 1024 * 1024) -> dict[str, bytes]:
    data = Path(path).read_bytes()
    if data[:8] != _SIG:
        raise CfbError("not a CFB file")
    sector_shift = _u16(data, 30)
    mini_shift = _u16(data, 32)
    if not (7 <= sector_shift <= 20) or mini_shift > sector_shift:
        raise CfbError("invalid sector shift")
    sector_size = 1 << sector_shift
    mini_size = 1 << mini_shift
    if len(data) < sector_size:
        raise CfbError("truncated header")

    num_fat = _u32(data, 44)
    first_dir = _u32(data, 48)
    mini_cutoff = _u32(data, 56)
    first_minifat = _u32(data, 60)
    num_minifat = _u32(data, 64)
    first_difat = _u32(data, 68)

    # DIFAT: 109 entries in the header, then a chain of DIFAT sectors.
    difat = [_u32(data, 76 + 4 * i) for i in range(109)]
    if first_difat not in (_ENDOFCHAIN, _FREESECT) and first_difat < 2 ** 31:
        sector = first_difat
        entries_per = sector_size // 4
        seen = set()
        while sector not in (_ENDOFCHAIN, _FREESECT) and sector not in seen:
            seen.add(sector)
            off = (sector + 1) * sector_size
            if off + sector_size > len(data):
                break
            for i in range(entries_per - 1):
                difat.append(_u32(data, off + 4 * i))
            sector = _u32(data, off + 4 * (entries_per - 1))
    difat = [d for d in difat if d < 2 ** 31][:max(num_fat, 1)]

    fat: list[int] = []
    for fs in difat:
        off = (fs + 1) * sector_size
        if off + sector_size > len(data):
            break
        for i in range(sector_size // 4):
            fat.append(_u32(data, off + 4 * i))
    if not fat:
        raise CfbError("empty FAT")

    # Directory entries.
    dir_bytes = _read_sectors(data, fat, first_dir, sector_size)
    entries: list[dict[str, Any]] = []
    for i in range(len(dir_bytes) // 128):
        de = dir_bytes[i * 128:(i + 1) * 128]
        name_len = _u16(de, 64)
        name = de[:max(0, name_len - 2)].decode("utf-16-le", "ignore") if name_len >= 2 else ""
        entries.append({
            "name": name, "type": de[66],
            "start": _u32(de, 116),
            "size": _u32(de, 120) if _u16(data, 26) == 3 else struct.unpack_from("<Q", de, 120)[0],
        })

    root = next((e for e in entries if e["type"] == 5), None)
    if root is None:
        raise CfbError("no root entry")

    # Mini FAT + mini stream (for small streams).
    minifat: list[int] = []
    if first_minifat not in (_ENDOFCHAIN, _FREESECT):
        mf = _read_sectors(data, fat, first_minifat, sector_size)
        minifat = [_u32(mf, i) for i in range(0, min(len(mf), num_minifat * sector_size), 4)]
    ministream = _read_sectors(data, fat, root["start"], sector_size) if root["size"] else b""

    out: dict[str, bytes] = {}
    total = 0
    for entry in entries:
        if entry["type"] != 2 or not entry["name"].startswith("__substg1.0_"):
            continue
        if len(out) >= max_streams or total >= max_total_bytes:
            break
        try:
            if entry["size"] < mini_cutoff and minifat:
                chunks: list[bytes] = []
                for s in _chain(ministream, minifat, int(entry["start"]), mini_size, len(minifat) + 1):
                    off = s * mini_size
                    chunks.append(ministream[off:off + mini_size])
                raw = b"".join(chunks)[:int(entry["size"])]
            else:
                raw = _read_sectors(data, fat, int(entry["start"]), sector_size)[:int(entry["size"])]
        except Exception:
            continue
        out[entry["name"]] = raw
        total += len(raw)
    return out
