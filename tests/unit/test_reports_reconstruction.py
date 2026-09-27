"""Evidence-based reconstruction units (M018, phase 32)."""
from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.reports.citations import CitationRegistry
from src.reports.models import ProvenanceClass
from src.reports.reconstruction import (
    reconstruct_archive,
    reconstruct_duplicates,
    reconstruct_email_thread,
    reconstruct_timeline,
    reconstruct_versions,
)


def _add(db: DatabaseManager, fid: int, path: str, text: str = "content here", *,
         modified: str = "2024-01-01 00:00:00", kind: str = "PHYSICAL_FILE",
         parent: int | None = None, member_path: str | None = None) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, archive_parent_id, archive_member_path, member_state, "
            "content_extracted) VALUES (?, ?, ?, '.txt', 20, ?, 'ACTIVE', ?, ?, ?, 'ACTIVE', 1)",
            (fid, path, Path(path).name, modified, kind, parent, member_path))
        conn.commit()
    if text:
        db.update_content(fid, text)


def test_version_chain_with_explicit_markers_is_ordered(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/rapport_v1.txt", "draft one")
    _add(db, 2, "/c/rapport_v2.txt", "draft two")
    _add(db, 3, "/c/rapport_v3.txt", "draft three")
    from src.dedup import VersionTracker
    VersionTracker(db).build()
    pack = reconstruct_versions(db, 2, mode="FULL_LOCAL", registry=CitationRegistry())
    assert pack.ordered is True
    assert pack.confidence == ProvenanceClass.KNOWN.value
    assert len(pack.items) == 3
    # Ranked, and exactly one explicitly justified primary.
    assert [i["rank"] for i in pack.items] == [0, 1, 2]
    primaries = [i for i in pack.items if i["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["primary_basis"]


def test_ambiguous_versions_are_unordered_no_final_claimed(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    # No explicit marker: only a generic "copy" word -> not enough to claim order.
    _add(db, 1, "/c/note.txt", "one", modified="2020-01-01 00:00:00")
    _add(db, 2, "/c/note copy.txt", "two", modified="2024-01-01 00:00:00")
    from src.dedup import VersionTracker
    VersionTracker(db).build()
    pack = reconstruct_versions(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    assert pack.ordered is False
    assert all(not i["is_primary"] for i in pack.items)
    assert pack.warnings or pack.notes


def test_no_version_family_is_unavailable_not_invented(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/solo.txt")
    pack = reconstruct_versions(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    assert pack.confidence == ProvenanceClass.UNAVAILABLE.value
    assert pack.items == [] and pack.warnings


def test_email_thread_uses_headers_only(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/1.eml", "From: a@b.com\r\nSubject: Root\r\n\r\nFirst")
    _add(db, 2, "/c/2.eml", "From: c@d.com\r\nSubject: Re: Root\r\n\r\nReply")
    _add(db, 3, "/c/3.eml", "From: e@f.com\r\nSubject: Unrelated\r\n\r\nOther")
    from src.ingest.thread_store import EmailThreadStore
    store = EmailThreadStore(db)
    store.record(1, {"message_id": "<root@x>", "subject": "Root", "date": "2024-01-01"})
    store.record(2, {"message_id": "<reply@x>", "in_reply_to": "<root@x>",
                     "references": "<root@x>", "subject": "Re: Root", "date": "2024-01-02"})
    store.record(3, {"message_id": "<other@x>", "subject": "Unrelated", "date": "2024-01-03"})
    pack = reconstruct_email_thread(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    ids = [i["file_id"] for i in pack.items]
    assert ids == [1, 2]  # same thread only, subject never used to join
    assert pack.ordered and pack.confidence == ProvenanceClass.KNOWN.value


def test_email_thread_unavailable_without_table(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/1.eml", "body")
    pack = reconstruct_email_thread(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    assert pack.confidence == ProvenanceClass.UNAVAILABLE.value


def test_archive_reconstruction_lists_members(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/box.zip", text="", kind="PHYSICAL_FILE")
    _add(db, 2, "/c/box.zip!/a.txt", "member a", kind="ARCHIVE_MEMBER", parent=1,
         member_path="a.txt")
    _add(db, 3, "/c/box.zip!/b.txt", "member b", kind="ARCHIVE_MEMBER", parent=1,
         member_path="b.txt")
    pack = reconstruct_archive(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    assert {i["member_path"] for i in pack.items} == {"a.txt", "b.txt"}
    assert pack.relations[0]["type"] == "ARCHIVE_CONTAINS"


def test_duplicate_reconstruction_exact_hash(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", "identical text")
    _add(db, 2, "/c/b.txt", "identical text")
    _add(db, 3, "/c/c.txt", "different text")
    from src.dedup import DedupStore
    store = DedupStore(db)
    store.set_hash(1, digest="deadbeef", size_bytes=20, modified_at="2024-01-01",
                   algorithm="sha256")
    store.set_hash(2, digest="deadbeef", size_bytes=20, modified_at="2024-01-01",
                   algorithm="sha256")
    store.set_hash(3, digest="cafebabe", size_bytes=20, modified_at="2024-01-01",
                   algorithm="sha256")
    pack = reconstruct_duplicates(db, 1, mode="FULL_LOCAL", registry=CitationRegistry())
    exact = [i for i in pack.items if i["relationship"] == "EXACT_DUPLICATE"]
    assert [i["file_id"] for i in exact] == [2]


def test_timeline_reconstruction_preserves_date_source(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "/c/a.txt", modified="2024-03-01 00:00:00")
    _add(db, 2, "/c/b.txt", modified="2024-04-01 00:00:00")
    pack = reconstruct_timeline(db, start="2024-01-01", end="2024-12-31",
                                mode="FULL_LOCAL", registry=CitationRegistry())
    assert len(pack.items) == 2
    assert all(i["date_source"] == "modified_at" for i in pack.items)
    assert pack.ordered
