"""Logging configuration for 36TB Intelligence."""

import sys
from pathlib import Path
from loguru import logger
from .simple_config import settings


def setup_logging() -> None:
    """Configure logging with loguru."""
    
    # Remove default handler
    logger.remove()
    
    # Console handler
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    
    logger.add(
        sys.stderr,
        format=log_format,
        level=settings.log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )
    
    # File handler
    log_file = settings.data_dir / "logs" / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        log_file,
        format=log_format,
        level="DEBUG",
        rotation="100 MB",
        retention="30 days",
        compression="gz",
        backtrace=True,
        diagnose=True,
    )
    
    # Performance logs (if enabled)
    if settings.profile_performance:
        perf_log = settings.data_dir / "logs" / "performance.log"
        logger.add(
            perf_log,
            format="{time} | {level} | {message}",
            level="INFO",
            filter=lambda record: "PERF" in record["message"],
            rotation="10 MB",
        )
    
    logger.info("Logging configured successfully")
    logger.debug(f"Log level: {settings.log_level}")
    logger.debug(f"Log file: {log_file}")


# Performance logging decorator
def log_performance(func_name: str = None):
    """Decorator to log function performance."""
    import time
    import functools
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not settings.profile_performance:
                return func(*args, **kwargs)
            
            name = func_name or f"{func.__module__}.{func.__name__}"
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"PERF | {name} | {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"PERF | {name} | FAILED after {execution_time:.3f}s | {e}")
                raise
        
        return wrapper
    return decorator