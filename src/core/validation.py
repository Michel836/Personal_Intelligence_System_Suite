"""Pydantic models for robust parameter validation."""

from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, validator, model_validator
from pydantic_settings import BaseSettings


class FileTypeEnum(str, Enum):
    """Valid file types."""
    DOCUMENT = "document"
    IMAGE = "image" 
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    CODE = "code"
    EMAIL = "email"
    OTHER = "other"


class PriorityEnum(str, Enum):
    """Priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SearchParams(BaseModel):
    """Parameters for search operations."""
    query: Optional[str] = Field(None, min_length=1, max_length=1000)
    limit: int = Field(20, ge=1, le=10000)
    offset: int = Field(0, ge=0)
    file_type: Optional[FileTypeEnum] = None
    priority: Optional[PriorityEnum] = None
    extension: Optional[str] = Field(None, pattern=r'^\.[a-zA-Z0-9]+$')
    min_size: Optional[int] = Field(None, ge=0)
    max_size: Optional[int] = Field(None, ge=0)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    
    @model_validator(mode='after')
    def validate_size_range(self):
        """Validate size range."""
        if self.min_size is not None and self.max_size is not None:
            if self.min_size > self.max_size:
                raise ValueError("min_size cannot be greater than max_size")
        return self
    
    @model_validator(mode='after')
    def validate_date_range(self):
        """Validate date range."""
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from cannot be after date_to")
        return self


class SemanticSearchParams(SearchParams):
    """Parameters for semantic search."""
    similarity_threshold: float = Field(0.3, ge=0.0, le=1.0)
    semantic_weight: float = Field(0.7, ge=0.0, le=1.0)
    text_weight: float = Field(0.3, ge=0.0, le=1.0)
    
    @model_validator(mode='after')
    def validate_weights(self):
        """Validate weights sum to 1.0."""
        if abs(self.semantic_weight + self.text_weight - 1.0) > 0.01:
            raise ValueError("semantic_weight and text_weight must sum to 1.0")
        return self


class ScanParams(BaseModel):
    """Parameters for scanning operations."""
    paths: List[str] = Field(..., min_items=1)
    max_depth: Optional[int] = Field(None, ge=0, le=20)
    follow_symlinks: bool = False
    skip_hidden: bool = True
    max_file_size: Optional[int] = Field(None, ge=0)
    include_extensions: Optional[List[str]] = None
    exclude_extensions: Optional[List[str]] = None
    max_workers: int = Field(4, ge=1, le=32)
    batch_size: int = Field(1000, ge=1, le=100000)
    
    @validator('paths')
    def validate_paths(cls, v):
        """Validate paths exist and are accessible."""
        valid_paths = []
        for path_str in v:
            path = Path(path_str)
            if not path.exists():
                raise ValueError(f"Path does not exist: {path_str}")
            if not path.is_dir():
                raise ValueError(f"Path is not a directory: {path_str}")
            valid_paths.append(str(path.resolve()))
        return valid_paths
    
    @validator('include_extensions', 'exclude_extensions')
    def validate_extensions(cls, v):
        """Validate extension format."""
        if v:
            for ext in v:
                if not ext.startswith('.'):
                    raise ValueError(f"Extension must start with '.': {ext}")
        return v


class ChatParams(BaseModel):
    """Parameters for chat operations."""
    message: str = Field(..., min_length=1, max_length=10000)
    model: Optional[str] = Field(None, pattern=r'^[a-zA-Z0-9_\-\.]+$')
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(1000, ge=1, le=8192)
    search_context: bool = True
    max_context_docs: int = Field(5, ge=0, le=20)


class FileInfo(BaseModel):
    """File information model."""
    path: str
    filename: str
    extension: Optional[str] = None
    size_bytes: int = Field(ge=0)
    file_type: FileTypeEnum
    priority: PriorityEnum
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    content_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    checksum: Optional[str] = Field(None, pattern=r'^[a-fA-F0-9]{32,64}$')
    
    @validator('path')
    def validate_path(cls, v):
        """Validate path format."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Path cannot be empty")
        return v.strip()
    
    @validator('filename')
    def validate_filename(cls, v):
        """Validate filename."""
        if not v or len(v.strip()) == 0:
            raise ValueError("Filename cannot be empty")
        
        # Check for invalid characters
        invalid_chars = '<>:"|?*'
        for char in invalid_chars:
            if char in v:
                raise ValueError(f"Filename contains invalid character: {char}")
        
        return v.strip()


class DatabaseConfig(BaseSettings):
    """Database configuration with validation."""
    db_path: str = Field("data/indexes/files.db")
    connection_timeout: float = Field(30.0, ge=1.0, le=300.0)
    max_retries: int = Field(3, ge=1, le=10)
    pool_size: int = Field(5, ge=1, le=50)
    cache_size: int = Field(10000, ge=1000, le=100000)
    
    class Config:
        env_prefix = "DB_"
        case_sensitive = False


class AIConfig(BaseSettings):
    """AI service configuration."""
    ollama_base_url: str = Field("http://localhost:11434")
    default_model: str = Field("llama3.2:latest")
    timeout: float = Field(30.0, ge=5.0, le=300.0)
    max_retries: int = Field(2, ge=1, le=5)
    embedding_model: str = Field("nomic-embed-text")
    embedding_dim: int = Field(384, ge=128, le=4096)
    
    class Config:
        env_prefix = "AI_"
        case_sensitive = False
    
    @validator('ollama_base_url')
    def validate_url(cls, v):
        """Validate URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        return v


class PerformanceConfig(BaseSettings):
    """Performance tuning configuration."""
    max_workers: int = Field(4, ge=1, le=32)
    batch_size: int = Field(1000, ge=100, le=100000)
    cache_ttl: int = Field(3600, ge=60, le=86400)  # seconds
    max_memory_usage: int = Field(8192, ge=1024, le=32768)  # MB
    enable_profiling: bool = False
    
    class Config:
        env_prefix = "PERF_"
        case_sensitive = False


class ValidationError(Exception):
    """Custom validation error."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.message = message
        self.field = field
        self.value = value
        super().__init__(message)


def validate_search_params(**kwargs) -> SearchParams:
    """Validate and return search parameters."""
    try:
        return SearchParams(**kwargs)
    except Exception as e:
        raise ValidationError(f"Invalid search parameters: {e}")


def validate_semantic_search_params(**kwargs) -> SemanticSearchParams:
    """Validate and return semantic search parameters."""
    try:
        return SemanticSearchParams(**kwargs)
    except Exception as e:
        raise ValidationError(f"Invalid semantic search parameters: {e}")


def validate_scan_params(**kwargs) -> ScanParams:
    """Validate and return scan parameters."""
    try:
        return ScanParams(**kwargs)
    except Exception as e:
        raise ValidationError(f"Invalid scan parameters: {e}")


def validate_chat_params(**kwargs) -> ChatParams:
    """Validate and return chat parameters."""
    try:
        return ChatParams(**kwargs)
    except Exception as e:
        raise ValidationError(f"Invalid chat parameters: {e}")


def validate_file_info(**kwargs) -> FileInfo:
    """Validate and return file info."""
    try:
        return FileInfo(**kwargs)
    except Exception as e:
        raise ValidationError(f"Invalid file info: {e}")


# Configuration instances
db_config = DatabaseConfig()
ai_config = AIConfig()
perf_config = PerformanceConfig()