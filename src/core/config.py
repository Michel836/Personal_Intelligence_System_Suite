"""Configuration management for 36TB Intelligence."""

import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field
try:
    from pydantic_settings import BaseSettings
except ImportError:
    # Fallback for older versions
    from pydantic import BaseSettings
from loguru import logger


class Settings(BaseSettings):
    """Application settings."""
    
    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tb36_index"
    postgres_user: str = "tb36_user"
    postgres_password: str = "your_secure_password"
    
    # Storage paths
    scan_paths: str = "C:\\"
    data_dir: Path = Path("./data")
    cache_dir: Path = Path("./data/cache")
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    llm_model: str = "mixtral:8x7b"
    vision_model: str = "llava"
    
    # Performance
    batch_size: int = 100
    max_workers: int = 8
    gpu_enabled: bool = True
    max_file_size_gb: int = 1
    
    # Security
    encryption_key: Optional[str] = None
    jwt_secret: str = "your_jwt_secret"
    allowed_hosts: List[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    
    # Development
    debug: bool = False
    log_level: str = "INFO"
    profile_performance: bool = False
    
    # Features
    enable_ocr: bool = True
    enable_email_extraction: bool = True
    enable_visualization: bool = True
    enable_auto_classification: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._setup_directories()
        self._validate_config()
    
    def _setup_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            self.data_dir,
            self.cache_dir,
            self.data_dir / "indexes",
            self.data_dir / "reports",
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {directory}")
    
    def _validate_config(self) -> None:
        """Validate configuration."""
        if not self.scan_paths:
            raise ValueError("At least one scan path must be specified")
        
        # Convert string to list for backward compatibility
        paths = self.scan_paths.split(",") if "," in self.scan_paths else [self.scan_paths]
        for path in paths:
            path = path.strip()
            if not Path(path).exists():
                logger.warning(f"Scan path does not exist: {path}")
    
    def get_scan_paths(self) -> List[str]:
        """Get scan paths as list."""
        if "," in self.scan_paths:
            return [p.strip() for p in self.scan_paths.split(",")]
        return [self.scan_paths]
    
    @property
    def database_url(self) -> str:
        """Construct database URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    
    @property
    def async_database_url(self) -> str:
        """Construct async database URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


# Global settings instance
settings = Settings()