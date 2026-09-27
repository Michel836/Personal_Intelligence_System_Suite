"""Archive indexing: discovery, member persistence and bounded extraction.

Separates container discovery/indexing from member content extraction
(M009J.18) and applies all safety limits cumulatively across nested archives.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from ..core.database import DatabaseManager
from .inspector import (
    ArchiveBudget,
    ArchiveFormat,
    ArchiveInspector,
    ArchiveLimitError,
    ArchiveMember,
    ArchiveStatus,
    MemberType,
)
from .limits import ARCHIVE_PROCESSING_VERSION, ArchiveLimits, ArchivePolicy

_ARCHIVE_FROM_EXT = {
    ".zip": ArchiveFormat.ZIP,
    ".7z": ArchiveFormat.SEVENZIP,
    ".rar": ArchiveFormat.RAR,
    ".tar": ArchiveFormat.TAR,
    ".tar.gz": ArchiveFormat.TAR_GZ,
    ".tgz": ArchiveFormat.TAR_GZ,
    ".tar.bz2": ArchiveFormat.TAR_BZ2,
    ".tbz2": ArchiveFormat.TAR_BZ2,
    ".tar.xz": ArchiveFormat.TAR_XZ,
    ".txz": ArchiveFormat.TAR_XZ,
    ".gz": ArchiveFormat.GZ,
    ".bz2": ArchiveFormat.BZ2,
    ".xz": ArchiveFormat.XZ,
}


def _format_from_name(name: str) -> Optional[ArchiveFormat]:
    lowered = name.lower()
    for ext in sorted(_ARCHIVE_FROM_EXT, key=len, reverse=True):
        if lowered.endswith(ext):
            return _ARCHIVE_FROM_EXT[ext]
    return None


# Outcomes that cannot change until the container bytes (fingerprint), the
# processing version, the policy or the limits change. TIMEOUT and
# BACKEND_UNAVAILABLE are transient and are never cached.
_DETERMINISTIC_STATUSES = frozenset({
    ArchiveStatus.OK.value,
    ArchiveStatus.CORRUPT_ARCHIVE.value,
    ArchiveStatus.UNSUPPORTED_FORMAT.value,
    ArchiveStatus.PASSWORD_REQUIRED.value,
    ArchiveStatus.LIMIT_DEPTH.value,
    ArchiveStatus.LIMIT_MEMBER_COUNT.value,
    ArchiveStatus.LIMIT_MEMBER_SIZE.value,
    ArchiveStatus.LIMIT_TOTAL_SIZE.value,
    ArchiveStatus.LIMIT_COMPRESSION_RATIO.value,
    ArchiveStatus.EXTENSION_MISMATCH.value,
    ArchiveStatus.NOT_ARCHIVE_FORMAT.value,
})


@dataclass
class ArchiveIndexResult:
    parent_id: int
    path: str
    status: str = ArchiveStatus.OK.value
    format: str = ""
    fingerprint: str = ""
    member_count: int = 0
    encrypted_count: int = 0
    expanded_size: int = 0
    compressed_size: int = 0
    extracted: int = 0
    failed: int = 0
    skipped: int = 0
    nested: int = 0
    missing: int = 0
    unchanged: bool = False
    elapsed: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return self.__dict__.copy()


class ArchiveIndexer:
    """Index archives into virtual member documents and extract their text."""

    def __init__(
        self,
        db: DatabaseManager,
        *,
        limits: Optional[ArchiveLimits] = None,
        policy: Optional[ArchivePolicy] = None,
        extraction_manager=None,
    ):
        self.db = db
        self.limits = limits or ArchiveLimits.from_env()
        self.policy = policy or ArchivePolicy.from_env()
        self._extraction_manager = extraction_manager

    # -- public API --------------------------------------------------------
    def index_archive(
        self,
        parent_id: int,
        parent_path: str,
        *,
        source_path: Optional[str] = None,
        force: bool = False,
        scan_id: Optional[int] = None,
        extract: Optional[bool] = None,
        depth: int = 1,
        budget: Optional[ArchiveBudget] = None,
        volume_id: Optional[int] = None,
    ) -> ArchiveIndexResult:
        """Index (and optionally extract) one archive by its DB row id.

        ``parent_path`` is the display/virtual path used as the member prefix;
        ``source_path`` is the real file to inspect (defaults to
        ``parent_path``). They differ only for nested archives.
        """
        start = time.time()
        source = source_path or parent_path
        result = ArchiveIndexResult(parent_id=parent_id, path=parent_path)
        if not self.policy.enabled:
            result.status = ArchiveStatus.DISABLED.value
            return result

        budget = budget if budget is not None else ArchiveBudget()
        inspector = ArchiveInspector(source, limits=self.limits, budget=budget, depth=depth - 1)
        result.format = inspector.format.value
        fingerprint = inspector.fingerprint()

        state = self.db.get_archive_index_state(parent_id) or {}
        cache_token = (
            f"{ARCHIVE_PROCESSING_VERSION}:{self.limits.cache_signature()}:{self.policy.policy}"
        )
        cached_status = state.get("archive_status")
        # Only trust the fast path when member virtual paths still follow the
        # current parent path (a renamed container must re-index). Deterministic
        # failures (corrupt / not-an-archive / limit hits) are cached too, so
        # they are not re-attempted on every unchanged scan.
        if (
            not force
            and state.get("archive_fingerprint") == fingerprint
            and state.get("archive_processing_version") == cache_token
            and cached_status in _DETERMINISTIC_STATUSES
            and self._members_match_parent(parent_id, parent_path)
        ):
            if cached_status == ArchiveStatus.OK.value:
                # Revive members cascaded MISSING while the container was absent
                # (the fingerprint proves the member set is unchanged).
                self.db.reactivate_archive_members(parent_id)
            result.unchanged = True
            result.status = cached_status or ArchiveStatus.OK.value
            result.member_count = state.get("archive_member_count") or 0
            result.encrypted_count = state.get("archive_encrypted_count") or 0
            return result

        members, status = inspector.list_members()
        result.status = status.value
        result.fingerprint = fingerprint
        result.encrypted_count = sum(1 for m in members if m.is_encrypted)
        result.member_count = sum(1 for m in members if m.is_file)
        result.expanded_size = sum(m.uncompressed_size for m in members)
        result.compressed_size = sum(m.compressed_size for m in members)

        member_dicts = [self._to_dict(m) for m in members]
        self.db.save_archive_members(
            parent_id, parent_path, member_dicts,
            volume_id=volume_id, scan_id=scan_id,
            archive_format=inspector.format.value, depth=depth,
        )
        seen_paths = [f"{parent_path}!/{m.member_path}" for m in members]
        recon = self.db.reconcile_archive_members(parent_id, seen_paths, scan_id=scan_id)
        result.missing = recon.get("missing", 0)

        self.db.set_archive_index_state(
            parent_id, fingerprint=fingerprint, status=status.value,
            member_count=result.member_count, encrypted_count=result.encrypted_count,
            compressed_size=result.compressed_size, expanded_size=result.expanded_size,
            format_name=inspector.format.value, processing_version=cache_token,
        )

        if status not in {ArchiveStatus.OK, ArchiveStatus.LIMIT_MEMBER_COUNT,
                          ArchiveStatus.LIMIT_TOTAL_SIZE, ArchiveStatus.LIMIT_COMPRESSION_RATIO,
                          ArchiveStatus.LIMIT_MEMBER_SIZE}:
            # A broken/locked archive must not leave stale ACTIVE virtual members.
            self.db.mark_archive_members_missing(parent_id)
            result.elapsed = time.time() - start
            return result

        should_extract = self.policy.extract_content if extract is None else extract
        if should_extract:
            self._extract_members(
                inspector, parent_id, parent_path, member_dicts, result,
                depth=depth, budget=budget, scan_id=scan_id, volume_id=volume_id,
            )
            if result.status == ArchiveStatus.LIMIT_EXTRACT_TIME.value:
                # Persist the transient status so the deterministic fast path does
                # not cache the archive and the next run resumes the PENDING set.
                self.db.set_archive_index_state(
                    parent_id, fingerprint=fingerprint, status=result.status,
                    member_count=result.member_count, encrypted_count=result.encrypted_count,
                    compressed_size=result.compressed_size, expanded_size=result.expanded_size,
                    format_name=inspector.format.value, processing_version=cache_token,
                )
        result.elapsed = time.time() - start
        return result

    # -- extraction --------------------------------------------------------
    def _extract_members(
        self,
        inspector: ArchiveInspector,
        parent_id: int,
        parent_path: str,
        member_dicts: List[Dict],
        result: ArchiveIndexResult,
        *,
        depth: int,
        budget: ArchiveBudget,
        scan_id: Optional[int],
        volume_id: Optional[int],
    ) -> None:
        rows = {r["archive_member_path"]: r for r in self.db.get_archive_members(parent_id)}
        manager = self._get_manager()
        # Per-archive total extraction budget: listing has its own timeout, but
        # extraction previously had none, so an archive with many slow members
        # could monopolise the pipeline indefinitely.
        deadline = time.monotonic() + self.limits.extract_timeout
        timed_out = False
        with tempfile.TemporaryDirectory(prefix="pis-arc-") as tmpdir:
            for md in member_dicts:
                row = rows.get(md["member_path"])
                if row is None:
                    continue
                # Resume-safe: members already resolved by a previous pass are
                # never re-read/re-extracted (terminal states are not PENDING).
                if str(row.get("extraction_state") or "PENDING").upper() != "PENDING":
                    continue
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                if not md.get("is_encrypted") and self._is_nested_archive(md) and depth < self.limits.max_depth:
                    if self._index_nested(inspector, row, md, depth, budget, scan_id, volume_id, tmpdir, result):
                        continue
                if md.get("member_type") != MemberType.FILE.value:
                    self.db.set_member_extraction(row["id"], content=None, state="SKIPPED")
                    result.skipped += 1
                    continue
                if md.get("is_encrypted"):
                    self.db.set_member_extraction(row["id"], content=None, state="ENCRYPTED")
                    result.skipped += 1
                    continue
                content = self._materialize_and_extract(inspector, md, manager, tmpdir)
                if content is None:
                    self.db.set_member_extraction(row["id"], content=None, state="SKIPPED")
                    result.skipped += 1
                elif content == "":
                    self.db.set_member_extraction(row["id"], content=None, state="FAILED")
                    result.failed += 1
                else:
                    self.db.set_member_extraction(row["id"], content=content, state="EXTRACTED")
                    result.extracted += 1
        if timed_out:
            result.status = ArchiveStatus.LIMIT_EXTRACT_TIME.value
            logger.warning(
                "archive extraction budget exhausted (%.1fs) for %s; "
                "remaining members stay PENDING for a later resume",
                self.limits.extract_timeout, parent_path,
            )

    def _index_nested(
        self, inspector, row, md, depth, budget, scan_id, volume_id, tmpdir, result
    ) -> bool:
        """Materialize a nested archive and index it recursively (bounded)."""
        try:
            member = ArchiveMember(
                member_path=md["member_path"], raw_name=md.get("raw_name") or md["member_path"],
                member_type=MemberType.FILE, uncompressed_size=int(md.get("uncompressed_size") or 0),
                compressed_size=int(md.get("compressed_size") or 0), crc=md.get("crc"),
            )
            data = inspector.open_member(member).read()
        except (ArchiveLimitError, OSError) as exc:
            self.db.set_member_extraction(row["id"], content=None, state="SKIPPED")
            logger.debug(f"nested archive read skipped: {exc}")
            return False
        ext = ".zip"
        for suffix in sorted(_ARCHIVE_FROM_EXT, key=len, reverse=True):
            if md["member_path"].lower().endswith(suffix):
                ext = suffix
                break
        nested_path = f"{row['path']}"
        safe_name = f"nested_{row['id']}{ext}"
        tmp_file = Path(tmpdir) / safe_name
        tmp_file.write_bytes(data)
        child = ArchiveIndexer(
            self.db, limits=self.limits, policy=self.policy,
            extraction_manager=self._extraction_manager,
        )
        child_result = child.index_archive(
            row["id"], nested_path, source_path=str(tmp_file), force=False,
            scan_id=scan_id, extract=True, depth=depth + 1, budget=budget, volume_id=volume_id,
        )
        self.db.set_member_extraction(
            row["id"], content=None,
            state="NESTED" if child_result.status == ArchiveStatus.OK.value else child_result.status,
        )
        result.nested += 1
        logger.debug(f"nested archive indexed: {nested_path} -> {child_result.status}")
        return True

    def _materialize_and_extract(self, inspector, md, manager, tmpdir: str) -> Optional[str]:
        """Materialize one member to a bounded temp file and extract its text.

        Returns the extracted text, ``""`` on extraction failure, or ``None``
        when the member is not a supported document type (skipped).
        """
        name = md["member_path"]
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
        try:
            member = ArchiveMember(
                member_path=name, raw_name=md.get("raw_name") or name,
                member_type=MemberType.FILE, uncompressed_size=int(md.get("uncompressed_size") or 0),
                compressed_size=int(md.get("compressed_size") or 0), crc=md.get("crc"),
            )
            data = inspector.open_member(member).read()
        except (ArchiveLimitError, OSError) as exc:
            logger.debug(f"member read failed for {name}: {exc}")
            return None
        if not data:
            return "" if md.get("uncompressed_size") else None
        tmp_file = Path(tmpdir) / f"member_{abs(hash(name)) % (10**10)}{ext}"
        tmp_file.write_bytes(data)
        try:
            if manager.get_extractor_for_file(tmp_file) is None:
                # Not a document type we can extract (e.g. images without OCR).
                from ..extractors.ocr import IMAGE_EXTENSIONS, ocr_enabled

                if not (ocr_enabled() and ext in IMAGE_EXTENSIONS):
                    return None
            res = manager.extract_single(tmp_file)
            if not res.success:
                return ""
            return res.content or ""
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"member extraction error for {name}: {exc}")
            return ""
        finally:
            try:
                tmp_file.unlink()
            except OSError:
                pass

    # -- helpers -----------------------------------------------------------
    def _get_manager(self):
        if self._extraction_manager is None:
            from ..extractors.manager import ExtractionManager

            self._extraction_manager = ExtractionManager()
        return self._extraction_manager

    @staticmethod
    def _is_nested_archive(md: Dict) -> bool:
        return _format_from_name(md.get("member_path", "")) is not None

    def _members_match_parent(self, parent_id: int, parent_path: str) -> bool:
        """True when every member's virtual path still uses ``parent_path``."""
        escaped = parent_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.db.get_connection() as conn:
            bad = conn.execute(
                "SELECT COUNT(*) FROM files WHERE document_kind = 'ARCHIVE_MEMBER' "
                "AND archive_parent_id = ? AND path NOT LIKE ? ESCAPE '\\'",
                (parent_id, f"{escaped}!/%"),
            ).fetchone()[0]
        return int(bad) == 0

    @staticmethod
    def _to_dict(m: ArchiveMember) -> Dict:
        return {
            "member_path": m.member_path,
            "raw_name": m.raw_name,
            "member_type": m.member_type.value,
            "uncompressed_size": m.uncompressed_size,
            "compressed_size": m.compressed_size,
            "crc": m.crc,
            "is_encrypted": m.is_encrypted,
            "modified_at": m.modified_at,
        }


def index_archives_in_db(
    db: DatabaseManager, *, limit: int = 100, scan_id: Optional[int] = None, force: bool = False
) -> List[ArchiveIndexResult]:
    """Index every discovered archive row (used by batch pipelines)."""
    indexer = ArchiveIndexer(db)
    if not indexer.policy.enabled:
        return []
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, path FROM files
               WHERE document_kind = 'PHYSICAL_FILE' AND file_type = 'archive'
               ORDER BY id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
    results: List[ArchiveIndexResult] = []
    for r in rows:
        results.append(indexer.index_archive(int(r["id"]), r["path"], force=force, scan_id=scan_id))
    return results
