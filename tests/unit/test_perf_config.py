"""Contract tests for the hardware-aware resource governor (M010-P)."""
from __future__ import annotations

from src.core.perf_config import (
    HardwareProfile,
    ResourceConfig,
    get_resource_config,
    reset_resource_config,
)


def test_profile_detects_bounded_values() -> None:
    profile = HardwareProfile.detect()
    assert profile.logical_cpus >= 1
    assert 1 <= profile.physical_cores <= profile.logical_cpus
    assert profile.ram_gb >= 0


def test_recommendations_are_bounded_and_positive() -> None:
    profile = HardwareProfile(logical_cpus=64, physical_cores=32, ram_gb=128.0,
                              gpu_name="GPU", vram_gb=24.0)
    rec = profile.recommended()
    assert 1 <= rec["scan_workers"] <= 16
    assert 1 <= rec["extract_workers"] <= 16
    assert 1 <= rec["blas_threads"] <= 16
    assert rec["db_batch_size"] > 0
    assert rec["embedding_batch_size"] > 0
    assert rec["max_ram_gb"] <= 128.0


def test_env_overrides_and_reset(monkeypatch) -> None:
    monkeypatch.setenv("PIS_DB_BATCH_SIZE", "123")
    monkeypatch.setenv("PIS_EMBEDDING_FP16", "0")
    monkeypatch.setenv("PIS_BULK_INDEX", "0")
    monkeypatch.setenv("PIS_SCAN_WORKERS", "3")
    reset_resource_config()
    cfg = get_resource_config()
    assert cfg.db_batch_size == 123
    assert cfg.embedding_fp16 is False
    assert cfg.bulk_index is False
    assert cfg.scan_workers == 3
    reset_resource_config()


def test_defaults_are_safe() -> None:
    reset_resource_config()
    cfg = ResourceConfig.resolve(
        HardwareProfile(logical_cpus=32, physical_cores=24, ram_gb=64.0,
                        gpu_name="RTX 3090", vram_gb=24.0)
    )
    # Durability is never weakened: bulk mode only defers FTS maintenance and
    # rebuilds it; pragma cache/mmap are bounded.
    assert cfg.db_cache_mb > 0
    assert cfg.db_mmap_mb >= 0
    assert cfg.bulk_index is True
