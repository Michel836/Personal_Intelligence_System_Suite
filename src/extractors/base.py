"""Base extractor class."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ExtractionResult:
    """Result of content extraction."""
    success: bool
    content: str = ""
    metadata: Dict[str, Any] = None
    error: Optional[str] = None
    extraction_time: float = 0.0
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseExtractor(ABC):
    """Base class for content extractors."""
    
    def __init__(self):
        self.supported_extensions = set()
    
    @abstractmethod
    def can_extract(self, file_path: Path) -> bool:
        """Check if this extractor can handle the file."""
        pass
    
    @abstractmethod
    def extract_content(self, file_path: Path) -> ExtractionResult:
        """Extract content from file."""
        pass
    
    def get_name(self) -> str:
        """Get extractor name."""
        return self.__class__.__name__