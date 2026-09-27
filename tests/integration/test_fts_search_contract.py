"""Contract tests for the FTS5-backed lexical search in ``DatabaseManager``.

Covers: single term, multi-term AND, exact phrase, filename/path matching,
content gating on ``update_content``, deterministic ranking, malformed input,
empty query, filter compatibility, insert/update/delete synchronisation,
rebuild of pre-existing databases and the LIKE fallback path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.core.database import DatabaseManager, build_fts_match
from src.scanner.models import FileType


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    return DatabaseManager(tmp_path / "fts.db")


@pytest.fixture
def add_file(db: DatabaseManager, file_info_factory):
    def _add(name: str, content: str | None = None, *, modified_at=None, **kwargs) -> int:
        file_info = file_info_factory(
            name,
            size_bytes=kwargs.pop("size_bytes", 10),
            modified_at=modified_at,
            **kwargs,
        )
        file_id = db.save_file(file_info)
        if content is not None:
            db.update_content(file_id, content)
        return file_id

    return _add


def _names(results):
    return [row["filename"] for row in results]


# --- A. single term --------------------------------------------------------
def test_single_term_search(db, add_file) -> None:
    add_file("s1.txt", "cancer marker")
    add_file("s2.txt", "unrelated content")
    assert _names(db.search_files(query="cancer")) == ["s1.txt"]


# --- B. multi-term AND -----------------------------------------------------
def test_multi_term_and_search(db, add_file) -> None:
    add_file("both_terms.txt", "cancer immunotherapy")
    add_file("one_term.txt", "cancer only")
    assert _names(db.search_files(query="cancer immunotherapy")) == ["both_terms.txt"]


# --- C. exact phrase -------------------------------------------------------
def test_exact_phrase_search(db, add_file) -> None:
    add_file("phrase_adjacent.txt", "cancer immunotherapy trial")
    add_file("phrase_split.txt", "cancer and immunotherapy")
    assert _names(db.search_files(query='"cancer immunotherapy"')) == [
        "phrase_adjacent.txt"
    ]


# --- D. filename / path matching ------------------------------------------
def test_filename_and_path_matching(db, add_file) -> None:
    add_file("report_2026.pdf")
    assert _names(db.search_files(query="report")) == ["report_2026.pdf"]
    assert _names(db.search_files(query="2026")) == ["report_2026.pdf"]


# --- E. content only after update_content ---------------------------------
def test_content_requires_update_content(db, add_file) -> None:
    file_id = add_file("no_content.txt")
    assert db.search_files(query="needle") == []
    db.update_content(file_id, "haystack needle thread")
    assert _names(db.search_files(query="needle")) == ["no_content.txt"]


# --- F. ranking stability --------------------------------------------------
def test_ranking_is_deterministic(db, add_file) -> None:
    add_file("rank_a.txt", "target alpha")
    add_file("rank_b.txt", "target beta")
    add_file("rank_c.txt", "target gamma")
    first = [row["id"] for row in db.search_files(query="target")]
    second = [row["id"] for row in db.search_files(query="target")]
    assert first == second
    assert len(first) == 3


# --- G. malformed / special characters ------------------------------------
@pytest.mark.parametrize(
    "query",
    ["AND", 'foo"bar', "---", "*", "NEAR(", "cancer OR", "(", ")", ":", '"', "a:b"],
)
def test_malformed_queries_do_not_raise(db, add_file, query) -> None:
    add_file("safe.txt", "cancer immunotherapy")
    assert isinstance(db.search_files(query=query), list)


def test_build_fts_match_parsing() -> None:
    assert build_fts_match("cancer") == '"cancer"*'
    assert build_fts_match("cancer immunotherapy") == '"cancer"* "immunotherapy"*'
    assert build_fts_match('"cancer immunotherapy"') == '"cancer immunotherapy"'
    assert build_fts_match("---") is None
    assert build_fts_match("") is None


# --- H. empty query --------------------------------------------------------
def test_empty_query_returns_all(db, add_file) -> None:
    add_file("a.txt")
    add_file("b.txt")
    assert len(db.search_files(query="")) == 2
    assert len(db.search_files(query="   ")) == 2


# --- I. filter compatibility ----------------------------------------------
def test_filter_compatibility(db, add_file) -> None:
    add_file(
        "filter_doc.txt",
        "shared term",
        extension=".txt",
        file_type=FileType.DOCUMENT,
        size_bytes=100,
    )
    add_file("filter_img.jpg", None, extension=".jpg", file_type=FileType.IMAGE, size_bytes=5000)

    assert _names(db.search_files(query="shared", extension=".txt")) == ["filter_doc.txt"]
    assert _names(db.search_files(query="filter", file_type=FileType.IMAGE)) == [
        "filter_img.jpg"
    ]
    assert _names(db.search_files(file_type=FileType.IMAGE, min_size=1000)) == [
        "filter_img.jpg"
    ]


# --- J. insert sync --------------------------------------------------------
def test_insert_sync(db, add_file) -> None:
    add_file("sync_insert_unique.txt")
    assert _names(db.search_files(query="unique")) == ["sync_insert_unique.txt"]


# --- K. update sync --------------------------------------------------------
def test_update_sync(db, add_file) -> None:
    file_id = add_file("sync_update.txt", "alpha term")
    assert len(db.search_files(query="alpha")) == 1
    db.update_content(file_id, "beta term")
    assert db.search_files(query="alpha") == []
    assert len(db.search_files(query="beta")) == 1


# --- L. delete sync --------------------------------------------------------
def test_delete_sync(db, add_file) -> None:
    file_id = add_file("zzdeletezz.txt")
    assert len(db.search_files(query="zzdeletezz")) == 1
    with db.get_connection() as conn:
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
    assert db.search_files(query="zzdeletezz") == []


# --- M. rebuild pre-existing database -------------------------------------
def test_rebuild_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"

    # Simulate a metadata-only DB created before trigger support.
    legacy = DatabaseManager(path)
    with legacy.get_connection() as conn:
        for trigger in ("files_fts_insert", "files_fts_delete", "files_fts_update"):
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        conn.execute("DELETE FROM fts_meta WHERE key = 'schema_version'")
        conn.execute(
            """INSERT INTO files
               (path, filename, extension, size_bytes, file_type, priority,
                created_at, modified_at, content_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "/x/legacy_unique.pdf",
                "legacy_unique.pdf",
                ".pdf",
                10,
                "document",
                "medium",
                "2024-01-01",
                "2024-01-01",
                "legacy rebuild content",
            ),
        )
        conn.commit()
        assert conn.execute(
            "SELECT count(*) FROM files_fts WHERE files_fts MATCH 'legacy'"
        ).fetchone()[0] == 0

    # Reopening installs the canonical triggers and rebuilds the index once.
    reopened = DatabaseManager(path)
    assert _names(reopened.search_files(query="legacy")) == ["legacy_unique.pdf"]
    with reopened.get_connection() as conn:
        assert conn.execute(
            "SELECT value FROM fts_meta WHERE key = 'schema_version'"
        ).fetchone()[0] == "1"


# --- N. fallback when FTS fails -------------------------------------------
def test_fallback_on_fts_failure(db, add_file, monkeypatch) -> None:
    add_file("fallback_unique.txt", "fallback needle content")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("simulated FTS failure")

    monkeypatch.setattr(db, "_search_files_fts", boom)
    assert _names(db.search_files(query="fallback needle")) == ["fallback_unique.txt"]


# --- Unicode tokenization + short-token policy (M004B.2) -------------------
@pytest.mark.parametrize(
    "query, expected",
    [
        ("résumé", '"résumé"*'),
        ("Müller", '"Müller"*'),
        ("Straße", '"Straße"*'),
        ("école", '"école"*'),
        ("français", '"français"*'),
        ("über", '"über"*'),
        ("naïve", '"naïve"*'),
        ("coöperate", '"coöperate"*'),
        ("中文", '"中文"*'),
        ("中文测试", '"中文测试"*'),
        ("Müller résumé", '"Müller"* "résumé"*'),
        ('"école française"', '"école française"'),
    ],
)
def test_unicode_and_short_token_match_expression(query, expected) -> None:
    assert build_fts_match(query) == expected


def test_single_character_tokens_are_exact() -> None:
    assert build_fts_match("R") == '"R"'
    assert build_fts_match("x") == '"x"'
    assert build_fts_match("A") == '"A"'
    assert build_fts_match("c++") == '"c"'
    assert build_fts_match("C#") == '"C"'


def test_unicode_search_uses_fts(db, add_file, monkeypatch) -> None:
    add_file("resume_unique.txt", "candidat résumé professionnel")
    add_file("muller_unique.txt", "Müller Straße Berlin")
    add_file("ecole_unique.txt", "école française primaire")
    add_file("cjk_unique.txt", "中文测试文档")

    def no_fallback(*args, **kwargs):
        raise AssertionError("Unicode queries must use the FTS path, not LIKE")

    monkeypatch.setattr(db, "_search_files_like", no_fallback)

    assert _names(db.search_files(query="résumé")) == ["resume_unique.txt"]
    assert _names(db.search_files(query="Müller")) == ["muller_unique.txt"]
    assert _names(db.search_files(query="Straße")) == ["muller_unique.txt"]
    assert _names(db.search_files(query="école")) == ["ecole_unique.txt"]
    assert _names(db.search_files(query="中文")) == ["cjk_unique.txt"]
    assert _names(db.search_files(query="中文测试")) == ["cjk_unique.txt"]


def test_unicode_case_insensitive(db, add_file) -> None:
    add_file("case_unicode.txt", "MÜLLER ÉCOLE")
    assert _names(db.search_files(query="müller")) == ["case_unicode.txt"]
    assert _names(db.search_files(query="école")) == ["case_unicode.txt"]


def test_quoted_unicode_phrase(db, add_file) -> None:
    add_file("phrase_adjacent.txt", "école française primaire")
    add_file("phrase_split.txt", "école et française")
    assert _names(db.search_files(query='"école française"')) == ["phrase_adjacent.txt"]


def test_short_tokens_do_not_broaden(db, add_file) -> None:
    add_file("cpp_unique.txt", "c plus plus and C# sharp")
    add_file("cancer_unique.txt", "cancer immunotherapy")

    # "c++"/"C#" tokenize to the single-character token "c"; it must NOT match
    # unrelated words such as "cancer" via prefix expansion.
    assert "cancer_unique.txt" not in _names(db.search_files(query="c++"))
    assert "cancer_unique.txt" not in _names(db.search_files(query="C#"))
    assert "cpp_unique.txt" in _names(db.search_files(query="c++"))


def test_single_letter_exact_token(db, add_file) -> None:
    add_file("letter_c.txt", "c language report")
    add_file("cancer_doc.txt", "cancer disease report")
    assert _names(db.search_files(query="c")) == ["letter_c.txt"]
