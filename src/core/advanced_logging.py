"""Advanced logging configuration with structured logging and debugging."""

import sys
import logging
import json
import inspect
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps
import threading

from loguru import logger

from .simple_config import settings


class StructuredLogger:
    """Enhanced structured logger with context and debugging features."""
    
    def __init__(self):
        self.context = threading.local()
        self.configured = False
    
    def configure(self):
        """Configure advanced logging system."""
        if self.configured:
            return
        
        # Remove default handler
        logger.remove()
        
        # Create logs directory
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Console handler with enhanced formatting
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{process.id}</cyan>:<cyan>{thread.id}</cyan> | "
            "<blue>{name}</blue>:<blue>{function}</blue>:<blue>{line}</blue> | "
            "<level>{message}</level>"
        )
        
        logger.add(
            sys.stderr,
            format=console_format,
            level=settings.log_level,
            colorize=True,
            backtrace=True,
            diagnose=True
        )
        
        # Main application log
        logger.add(
            log_dir / "app.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process.id}:{thread.id} | {name}:{function}:{line} | {message}",
            level=settings.log_level,
            rotation="50 MB",
            retention="30 days",
            compression="gz",
            backtrace=True,
            diagnose=True
        )
        
        # Error log (errors and critical only)
        logger.add(
            log_dir / "errors.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process.id}:{thread.id} | {name}:{function}:{line} | {message}",
            level="ERROR",
            rotation="10 MB",
            retention="90 days",
            compression="gz",
            backtrace=True,
            diagnose=True
        )
        
        # Performance log (structured JSON)
        logger.add(
            log_dir / "performance.jsonl",
            format=self._json_formatter,
            level="INFO",
            filter=lambda record: record["extra"].get("performance", False),
            rotation="20 MB",
            retention="7 days",
            compression="gz"
        )
        
        # Audit log (sensitive operations)
        logger.add(
            log_dir / "audit.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process.id}:{thread.id} | {name}:{function}:{line} | {message}",
            level="INFO",
            filter=lambda record: record["extra"].get("audit", False),
            rotation="10 MB",
            retention="365 days",  # Keep audit logs for 1 year
            compression="gz"
        )
        
        # Debug log (verbose debugging info)
        if settings.log_level == "DEBUG":
            logger.add(
                log_dir / "debug.log",
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process.id}:{thread.id} | {name}:{function}:{line} | {extra[context]} | {message}",
                level="DEBUG",
                rotation="100 MB",
                retention="3 days",
                compression="gz",
                backtrace=True,
                diagnose=True
            )
        
        self.configured = True
        logger.info("Advanced logging system configured")
    
    def _json_formatter(self, record):
        """Format log record as JSON for structured logging."""
        json_record = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "process_id": record["process"].id,
            "thread_id": record["thread"].id,
            "module": record["name"],
            "function": record["function"],
            "line": record["line"],
            "message": record["message"]
        }
        
        # Add extra fields
        for key, value in record["extra"].items():
            json_record[key] = value
        
        return json.dumps(json_record)
    
    def set_context(self, **kwargs):
        """Set logging context for current thread."""
        if not hasattr(self.context, 'data'):
            self.context.data = {}
        self.context.data.update(kwargs)
    
    def get_context(self) -> Dict[str, Any]:
        """Get current logging context."""
        return getattr(self.context, 'data', {})
    
    def clear_context(self):
        """Clear logging context."""
        if hasattr(self.context, 'data'):
            self.context.data.clear()


# Global structured logger instance
structured_logger = StructuredLogger()


def setup_advanced_logging():
    """Configure advanced logging for the application."""
    structured_logger.configure()


def log_performance_advanced(func_name: str, duration: float, **kwargs):
    """Log performance metrics with structured data."""
    perf_data = {
        "performance": True,
        "function": func_name,
        "duration_seconds": duration,
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }
    
    logger.bind(**perf_data).info(f"Performance: {func_name} took {duration:.3f}s")


def log_audit(action: str, resource: str = None, user: str = None, **kwargs):
    """Log audit events."""
    audit_data = {
        "audit": True,
        "action": action,
        "resource": resource,
        "user": user or "system",
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }
    
    logger.bind(**audit_data).info(f"AUDIT: {action} on {resource or 'unknown'} by {user or 'system'}")


def debug_log(message: str, **kwargs):
    """Enhanced debug logging with context."""
    context = structured_logger.get_context()
    debug_data = {
        "context": json.dumps(context),
        **kwargs
    }
    
    logger.bind(**debug_data).debug(message)


def trace_calls(include_args: bool = False, include_result: bool = False):
    """Decorator to trace function calls."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__qualname__}"
            
            # Log function entry
            entry_data = {"trace": True, "event": "enter", "function": func_name}
            
            if include_args:
                try:
                    # Get function signature
                    sig = inspect.signature(func)
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()
                    
                    # Sanitize arguments (remove sensitive data)
                    sanitized_args = {}
                    for name, value in bound_args.arguments.items():
                        if any(sensitive in name.lower() for sensitive in ['password', 'secret', 'token', 'key']):
                            sanitized_args[name] = "***REDACTED***"
                        else:
                            sanitized_args[name] = repr(value)[:100]  # Limit length
                    
                    entry_data["arguments"] = sanitized_args
                except Exception:
                    entry_data["arguments"] = "Unable to capture arguments"
            
            logger.bind(**entry_data).debug(f"TRACE: Entering {func_name}")
            
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                
                # Log function exit
                duration = (datetime.now() - start_time).total_seconds()
                exit_data = {
                    "trace": True,
                    "event": "exit",
                    "function": func_name,
                    "duration_seconds": duration,
                    "success": True
                }
                
                if include_result and result is not None:
                    exit_data["result"] = repr(result)[:200]  # Limit length
                
                logger.bind(**exit_data).debug(f"TRACE: Exiting {func_name} (took {duration:.3f}s)")
                
                return result
                
            except Exception as e:
                # Log function exception
                duration = (datetime.now() - start_time).total_seconds()
                error_data = {
                    "trace": True,
                    "event": "exception",
                    "function": func_name,
                    "duration_seconds": duration,
                    "success": False,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                    "traceback": traceback.format_exc()
                }
                
                logger.bind(**error_data).error(f"TRACE: Exception in {func_name} after {duration:.3f}s: {e}")
                raise
        
        return wrapper
    return decorator


def performance_monitor(threshold_seconds: float = 1.0):
    """Decorator to monitor function performance and warn on slow operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = datetime.now()
            result = func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()
            
            func_name = f"{func.__module__}.{func.__qualname__}"
            
            if duration > threshold_seconds:
                logger.warning(
                    f"SLOW OPERATION: {func_name} took {duration:.3f}s (threshold: {threshold_seconds}s)",
                    performance=True,
                    function=func_name,
                    duration_seconds=duration,
                    threshold_seconds=threshold_seconds,
                    slow_operation=True
                )
            else:
                log_performance_advanced(func_name, duration)
            
            return result
        
        return wrapper
    return decorator


def error_handler(reraise: bool = True, log_level: str = "ERROR"):
    """Decorator to handle and log exceptions."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                func_name = f"{func.__module__}.{func.__qualname__}"
                
                error_data = {
                    "error_handler": True,
                    "function": func_name,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                    "traceback": traceback.format_exc(),
                    "context": structured_logger.get_context()
                }
                
                if log_level == "ERROR":
                    logger.bind(**error_data).error(f"ERROR in {func_name}: {e}")
                elif log_level == "WARNING":
                    logger.bind(**error_data).warning(f"WARNING in {func_name}: {e}")
                else:
                    logger.bind(**error_data).info(f"HANDLED EXCEPTION in {func_name}: {e}")
                
                if reraise:
                    raise
                else:
                    return None
        
        return wrapper
    return decorator


class LogContext:
    """Context manager for adding temporary logging context."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self.previous_context = None
    
    def __enter__(self):
        self.previous_context = structured_logger.get_context().copy()
        structured_logger.set_context(**self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        structured_logger.clear_context()
        if self.previous_context:
            structured_logger.set_context(**self.previous_context)


# Convenience functions for common logging patterns
def log_search_query(query: str, search_type: str, results_count: int, duration: float):
    """Log search operations for analytics."""
    logger.bind(
        audit=True,
        action="search",
        query=query,
        search_type=search_type,
        results_count=results_count,
        duration_seconds=duration,
        timestamp=datetime.now().isoformat()
    ).info(f"Search: '{query}' ({search_type}) returned {results_count} results in {duration:.3f}s")


def log_file_operation(operation: str, file_path: str, success: bool = True, error: str = None):
    """Log file operations."""
    level = "info" if success else "error"
    message = f"File {operation}: {file_path}"
    
    if not success and error:
        message += f" - Error: {error}"
    
    logger.bind(
        audit=True,
        action=f"file_{operation}",
        file_path=file_path,
        success=success,
        error=error,
        timestamp=datetime.now().isoformat()
    ).log(level.upper(), message)


def log_ai_interaction(model: str, input_tokens: int, output_tokens: int, duration: float):
    """Log AI model interactions."""
    logger.bind(
        performance=True,
        audit=True,
        action="ai_interaction",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_seconds=duration,
        timestamp=datetime.now().isoformat()
    ).info(f"AI Interaction: {model} processed {input_tokens} input tokens, generated {output_tokens} output tokens in {duration:.3f}s")