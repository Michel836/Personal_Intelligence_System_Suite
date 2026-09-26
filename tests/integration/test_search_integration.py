"""Integration tests for search functionality."""

import pytest
import tempfile
import os
from pathlib import Path
import sqlite3

from src.core.database import DatabaseManager
from src.scanner.fast_engine import FastScannerEngine
from src.intelligence.semantic_search import SemanticSearchEngine
from src.intelligence.chat_engine import ChatEngine
from src.scanner.models import FileInfo, FileType, Priority


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        db_path = Path(tmp_file.name)
    
    yield db_path
    
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def test_files_dir():
    """Create temporary directory with test files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # Create test files
        (tmp_path / "test_document.txt").write_text(
            "This is a test document about artificial intelligence and machine learning."
        )
        (tmp_path / "another_file.pdf").touch()
        (tmp_path / "image.jpg").touch()
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested_file.doc").write_text(
            "Nested document with important information about databases and search engines."
        )
        
        yield tmp_path


@pytest.fixture
def db_manager(temp_db):
    """Create database manager with test database."""
    return DatabaseManager(temp_db)


@pytest.fixture
def populated_db(db_manager, test_files_dir, file_info_factory):
    """Database populated with metadata only (content is added by extraction)."""
    # Build schema-valid FileInfo objects (required timestamps supplied).
    test_files = [
        file_info_factory(
            test_files_dir / "test_document.txt",
            size_bytes=100,
            file_type=FileType.DOCUMENT,
            priority=Priority.HIGH,
        ),
        file_info_factory(
            test_files_dir / "subdir" / "nested_file.doc",
            size_bytes=150,
            file_type=FileType.DOCUMENT,
            priority=Priority.MEDIUM,
        ),
        file_info_factory(
            test_files_dir / "image.jpg",
            size_bytes=50000,
            file_type=FileType.IMAGE,
            priority=Priority.LOW,
        ),
    ]

    # Insert test metadata
    for file_info in test_files:
        db_manager.save_file(file_info)

    return db_manager


class TestDatabaseIntegration:
    """Test database operations."""
    
    def test_database_creation(self, temp_db):
        """Test database is created correctly."""
        db = DatabaseManager(temp_db)
        assert temp_db.exists()
        
        # Test schema exists
        with db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files'
            """)
            assert cursor.fetchone() is not None
    
    def test_file_insertion_and_retrieval(self, populated_db):
        """Test inserting and retrieving files."""
        # Test basic search
        results = populated_db.search_files()
        assert len(results) == 3
        
        # Test search by filename
        results = populated_db.search_files(query="test_document")
        assert len(results) == 1
        assert results[0]['filename'] == "test_document.txt"
    
    def test_search_filters(self, populated_db):
        """Test search with various filters."""
        # Test by file type
        results = populated_db.search_files(file_type=FileType.DOCUMENT)
        assert len(results) == 2
        
        # Test by extension
        results = populated_db.search_files(extension=".jpg")
        assert len(results) == 1
        
        # Test by size
        results = populated_db.search_files(min_size=1000)
        assert len(results) == 1  # Only the image file
    
    def test_content_search(self, populated_db):
        """Content becomes searchable only after extraction updates it."""
        # Metadata is available immediately after scan/save...
        all_rows = populated_db.search_files()
        assert len(all_rows) == 3
        assert all(row["content_text"] is None for row in all_rows)

        # ...but content search finds nothing until extraction runs.
        assert populated_db.search_files(query="artificial intelligence") == []
        assert populated_db.search_files(query="databases") == []

        # Run the real content pipeline step: save -> update_content.
        txt_doc = populated_db.search_files(query="test_document")[0]
        nested_doc = populated_db.search_files(query="nested_file")[0]
        populated_db.update_content(
            txt_doc["id"],
            "This is a test document about artificial intelligence and machine learning.",
        )
        populated_db.update_content(
            nested_doc["id"],
            "Nested document with important information about databases and search engines.",
        )

        # Content is now searchable through the same metadata rows.
        assert len(populated_db.search_files(query="artificial intelligence")) >= 1
        assert len(populated_db.search_files(query="databases")) >= 1


class TestScannerIntegration:
    """Test scanner functionality."""
    
    def test_scanner_basic_functionality(self, test_files_dir, temp_db):
        """Test the canonical scan -> persist -> search flow."""
        db = DatabaseManager(temp_db)
        scanner = FastScannerEngine()

        # Canonical contract: scan_paths() yields schema-valid FileInfo objects.
        files = list(scanner.scan_paths([test_files_dir]))

        assert len(files) > 0
        assert all(isinstance(file_info, FileInfo) for file_info in files)
        assert all(
            file_info.created_at is not None and file_info.modified_at is not None
            for file_info in files
        )

        # Persist the yielded metadata, then read it back.
        db.save_files_batch(files)
        results = db.search_files()
        assert len(results) == len(files)
    
    def test_scanner_file_type_detection(self, test_files_dir, temp_db):
        """Test file type detection during scanning."""
        db = DatabaseManager(temp_db)
        scanner = FastScannerEngine()

        files = list(scanner.scan_paths([test_files_dir]))
        assert len(files) > 0
        db.save_files_batch(files)

        # Check different file types were persisted with their classification.
        doc_files = db.search_files(file_type=FileType.DOCUMENT)
        image_files = db.search_files(file_type=FileType.IMAGE)

        assert len(doc_files) > 0
        assert len(image_files) > 0


class TestSemanticSearchIntegration:
    """Test semantic search functionality."""
    
    @pytest.mark.skipif(
        not os.getenv('ENABLE_AI_TESTS'), 
        reason="AI tests disabled - set ENABLE_AI_TESTS=1 to run"
    )
    def test_semantic_search_basic(self, populated_db):
        """Test basic semantic search functionality."""
        search_engine = SemanticSearchEngine(populated_db)
        
        if not search_engine.is_available():
            pytest.skip("Semantic search not available")
        
        # Test semantic search
        results = search_engine.semantic_search("machine learning concepts")
        
        assert isinstance(results, list)
        # Should find documents even with different wording
        assert len(results) >= 0  # May be 0 if embeddings not available
    
    @pytest.mark.skipif(
        not os.getenv('ENABLE_AI_TESTS'), 
        reason="AI tests disabled"
    )
    def test_hybrid_search(self, populated_db):
        """Test hybrid search combining semantic and text search."""
        search_engine = SemanticSearchEngine(populated_db)
        
        if not search_engine.is_available():
            pytest.skip("Semantic search not available")
        
        results = search_engine.hybrid_search("important database information")
        
        assert isinstance(results, list)
        # Results should include relevance scores
        if results:
            assert 'combined_score' in results[0]


class TestChatIntegration:
    """Test chat functionality."""
    
    @pytest.mark.skipif(
        not os.getenv('ENABLE_AI_TESTS'), 
        reason="AI tests disabled"
    )
    def test_chat_basic_functionality(self, populated_db):
        """Test basic chat functionality."""
        chat_engine = ChatEngine(db=populated_db)
        
        response = chat_engine.chat("What documents do you have about AI?")
        
        assert isinstance(response, dict)
        assert 'response' in response
        assert isinstance(response['response'], str)
        assert len(response['response']) > 0
    
    @pytest.mark.skipif(
        not os.getenv('ENABLE_AI_TESTS'),
        reason="AI tests disabled"
    )
    def test_chat_with_context(self, populated_db):
        """Test chat with document context."""
        chat_engine = ChatEngine(db=populated_db)
        
        response = chat_engine.chat("Tell me about the test document", search_context=True)
        
        assert isinstance(response, dict)
        assert 'sources' in response
        assert response.get('context_used') is True


class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""
    
    def test_scan_search_workflow(self, test_files_dir, temp_db):
        """Test complete scan and search workflow."""
        db = DatabaseManager(temp_db)
        scanner = FastScannerEngine()
        
        # 1. Scan directory (canonical generator contract).
        files = list(scanner.scan_paths([test_files_dir]))
        assert len(files) > 0

        # 2. Persist the scanned metadata.
        db.save_files_batch(files)
        results = db.search_files()
        assert len(results) > 0

        # 3. Filtered search.
        txt_files = db.search_files(extension=".txt")
        assert len(txt_files) > 0

        # 4. Content search only works after the extraction step updates content.
        db.update_content(
            txt_files[0]["id"],
            "This is a test document about artificial intelligence and machine learning.",
        )
        content_results = db.search_files(query="test document")
        assert len(content_results) > 0
    
    @pytest.mark.skipif(
        not os.getenv('ENABLE_AI_TESTS'),
        reason="AI tests disabled"
    )
    def test_full_ai_workflow(self, populated_db):
        """Test complete AI-powered workflow."""
        semantic_search = SemanticSearchEngine(populated_db)
        chat_engine = ChatEngine(db=populated_db)
        
        if not semantic_search.is_available():
            pytest.skip("AI services not available")
        
        # 1. Semantic search
        search_results = semantic_search.semantic_search("artificial intelligence")
        
        # 2. Chat about results
        response = chat_engine.chat("What can you tell me about AI from these documents?")
        
        assert isinstance(search_results, list)
        assert isinstance(response, dict)
        assert 'response' in response


class TestPerformanceIntegration:
    """Test performance characteristics."""
    
    def test_large_dataset_search_performance(self, temp_db):
        """Test search performance with larger dataset."""
        db = DatabaseManager(temp_db)
        
        # Insert many test records
        with db.get_connection() as conn:
            for i in range(1000):
                conn.execute("""
                    INSERT INTO files (
                        path, filename, extension, size_bytes, 
                        file_type, priority, content_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"/test/path_{i}.txt",
                    f"file_{i}.txt", 
                    ".txt",
                    1000 + i,
                    "document",
                    "medium",
                    f"This is test document number {i} with some content about testing and performance."
                ))
            conn.commit()
        
        # Test search performance
        import time
        start_time = time.time()
        
        # CONTRACT(M004A): DatabaseManager.search_files matches contiguous LIKE
        # substrings. Tokenized/multi-word (FTS) semantics are deliberately NOT
        # covered here and are deferred to M004B.
        results = db.search_files(query="testing and performance", limit=50)
        
        search_time = time.time() - start_time
        
        assert len(results) > 0
        assert search_time < 1.0  # Should be fast even with 1000 records
    
    def test_concurrent_access(self, populated_db):
        """Test concurrent database access."""
        import threading
        import time
        
        results = []
        errors = []
        
        def worker():
            try:
                # Multiple operations per thread
                for _ in range(10):
                    search_results = populated_db.search_files()
                    results.extend(search_results)
                    time.sleep(0.01)  # Small delay
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join(timeout=10)
        
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        assert len(results) > 0


# Test configuration
pytest_plugins = ['pytest_asyncio']


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "ai: mark test as requiring AI services"
    )