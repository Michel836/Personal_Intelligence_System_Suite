"""Simple configuration without pydantic-settings."""

import os
from pathlib import Path
from typing import List
from loguru import logger

from .paths import cache_dir, data_dir, indexes_dir, logs_dir, reports_dir


class SimpleSettings:
    """Simple settings class."""

    def __init__(self):
        # Absolute, CWD-independent paths (XDG by default; see core.paths).
        self.data_dir = data_dir()
        self.cache_dir = cache_dir()

        # Performance settings
        self.max_workers = int(os.getenv("MAX_WORKERS", "4"))
        self.batch_size = int(os.getenv("BATCH_SIZE", "100"))
        self.max_file_size_gb = int(os.getenv("MAX_FILE_SIZE_GB", "1"))

        # Debug
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.profile_performance = os.getenv("PROFILE_PERFORMANCE", "false").lower() == "true"

        # Create directories
        self._setup_directories()

    def _setup_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            self.data_dir,
            self.cache_dir,
            indexes_dir(),
            reports_dir(),
            logs_dir(),
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {directory}")


# Global settings instance
settings = SimpleSettings()
