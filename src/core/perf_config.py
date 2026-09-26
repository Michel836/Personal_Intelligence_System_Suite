"""Hardware-aware performance profile and resource governor (M010-P).

Central, *configurable* source of execution-tuning knobs. Every setting has a
conservative default derived from the detected hardware and can be overridden by
an environment variable, so nothing is hard-coded to a specific machine.

This module has no import-time side effects and does not import numpy/torch, so it
is safe to import from the scanner, database, extractors and UI layers.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HardwareProfile:
    """Detected hardware capabilities (never assumes a specific machine)."""

    logical_cpus: int
    physical_cores: int
    ram_gb: float
    gpu_name: str | None
    vram_gb: float

    @classmethod
    def detect(cls) -> HardwareProfile:
        logical = os.cpu_count() or 1
        physical = logical
        ram_gb = 0.0
        try:
            import psutil

            physical = psutil.cpu_count(logical=False) or logical
            ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            physical = max(1, logical // 2)
        gpu_name: str | None = None
        vram_gb = 0.0
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout.strip()
            if out:
                parts = [p.strip() for p in out.splitlines()[0].split(",")]
                gpu_name = parts[0]
                vram_gb = round(int(parts[1]) / 1024, 1)
        except Exception:
            gpu_name = None
        return cls(logical, physical, ram_gb, gpu_name, vram_gb)

    def recommended(self) -> dict[str, float]:
        """Measured defaults for this hardware class (M010-P), bounded and safe.

        Concurrency does not help the CPU/GIL-bound scanner, extractor or
        archive paths (see the M010-P benchmarks), so those default to their
        measured optimum rather than the physical core count. Embedding and BLAS
        values are the measured GPU/matvec optima.
        """
        return {
            "scan_workers": 1,
            "extract_workers": 1,
            "ocr_workers": 8,
            "archive_workers": 1,
            "db_batch_size": 1000,
            "embedding_batch_size": 128,
            "blas_threads": max(1, min(16, self.physical_cores)),
            "max_ram_gb": round(self.ram_gb * 0.6, 1) if self.ram_gb else 16.0,
        }


@dataclass(frozen=True)
class ResourceConfig:
    """Resolved performance settings (env override > profile recommendation)."""

    scan_workers: int
    extract_workers: int
    ocr_workers: int
    archive_workers: int
    db_batch_size: int
    db_cache_mb: int
    db_mmap_mb: int
    embedding_batch_size: int
    embedding_fp16: bool
    blas_threads: int
    max_ram_gb: float
    bulk_index: bool
    scan_overlap: bool
    profile: HardwareProfile

    @classmethod
    def resolve(
        cls, profile: HardwareProfile | None = None
    ) -> ResourceConfig:
        profile = profile or HardwareProfile.detect()
        rec = profile.recommended()
        return cls(
            scan_workers=_env_int("PIS_SCAN_WORKERS", int(rec["scan_workers"]), minimum=1),
            extract_workers=_env_int("PIS_EXTRACT_WORKERS", int(rec["extract_workers"]), minimum=1),
            ocr_workers=_env_int("PIS_OCR_WORKERS", int(rec["ocr_workers"]), minimum=1),
            archive_workers=_env_int("PIS_ARCHIVE_WORKERS", int(rec["archive_workers"]), minimum=1),
            db_batch_size=_env_int("PIS_DB_BATCH_SIZE", int(rec["db_batch_size"]), minimum=1),
            db_cache_mb=_env_int("PIS_DB_CACHE_MB", 64, minimum=1),
            db_mmap_mb=_env_int("PIS_DB_MMAP_MB", 256, minimum=0),
            embedding_batch_size=_env_int("PIS_EMBEDDING_BATCH_SIZE", int(rec["embedding_batch_size"]), minimum=1),
            embedding_fp16=_env_bool("PIS_EMBEDDING_FP16", True),
            blas_threads=_env_int("PIS_BLAS_THREADS", int(rec["blas_threads"]), minimum=1),
            max_ram_gb=float(_env_int("PIS_MAX_RAM_GB", int(rec["max_ram_gb"]), minimum=1)),
            bulk_index=_env_bool("PIS_BULK_INDEX", True),
            scan_overlap=_env_bool("PIS_SCAN_OVERLAP", False),
            profile=profile,
        )

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["profile"] = asdict(self.profile)
        return data


_config: ResourceConfig | None = None


def get_resource_config() -> ResourceConfig:
    """Return the process-wide resolved resource config (lazily computed)."""
    global _config
    if _config is None:
        _config = ResourceConfig.resolve()
    return _config


def reset_resource_config() -> None:
    """Clear the cached config (tests / after changing env)."""
    global _config
    _config = None
