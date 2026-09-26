"""Regression: every DB-backed component must honor ``PIS_DB_PATH``.

The trial exposed components that hard-coded ``data/indexes/files.db`` and thus
silently bypassed an isolated (e.g. trial) database.
"""
from __future__ import annotations

from pathlib import Path

from src.ai.advanced_ai import AdvancedAI
from src.analytics.dashboard import AnalyticsDashboard
from src.cloud.sync_manager import CloudSyncManager
from src.core.database import DatabaseManager, default_db_path
from src.extractors.auto_extractor import AutoExtractor
from src.search.advanced_search import AdvancedSearch
from src.search.legal_search import LegalDocumentSearch
from src.tags.tag_manager import TagManager
from src.visualizations.advanced_viz import AdvancedVisualizations


def test_components_honor_pis_db_path(tmp_path: Path, monkeypatch) -> None:
    target = str(tmp_path / "isolated.db")
    monkeypatch.setenv("PIS_DB_PATH", target)

    assert default_db_path() == target
    assert str(DatabaseManager().db_path) == target

    components = [
        AutoExtractor(),
        AnalyticsDashboard(),
        AdvancedSearch(),
        LegalDocumentSearch(),
        TagManager(),
        AdvancedVisualizations(),
        AdvancedAI(),
        CloudSyncManager(),
    ]
    for component in components:
        assert str(component.db_path) == target, type(component).__name__


def test_explicit_db_path_overrides_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIS_DB_PATH", str(tmp_path / "env.db"))
    explicit = str(tmp_path / "explicit.db")
    assert str(AutoExtractor(db_path=explicit).db_path) == explicit
