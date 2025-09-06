"""Robust error handling with retry logic and circuit breakers."""

import functools
import time
import random
import threading
from typing import Callable, Any, Type, Tuple, Optional, Dict
from dataclasses import dataclass
from enum import Enum

from loguru import logger


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: Type[Exception] = Exception


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self._lock = threading.Lock()
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset from OPEN to HALF_OPEN."""
        return (
            self.state == CircuitState.OPEN and
            time.time() - self.last_failure_time >= self.config.recovery_timeout
        )
    
    def _reset(self):
        """Reset circuit breaker to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
    
    def _record_success(self):
        """Record successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            self._reset()
            logger.info("Circuit breaker reset to CLOSED after successful operation")
    
    def _record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator to apply circuit breaker pattern."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self._lock:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker moved to HALF_OPEN state")
                
                if self.state == CircuitState.OPEN:
                    raise Exception(f"Circuit breaker is OPEN - operation blocked")
            
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self._record_success()
                return result
                
            except self.config.expected_exception as e:
                with self._lock:
                    self._record_failure()
                raise
        
        return wrapper
    
    def get_state(self) -> dict:
        """Get current circuit breaker state."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "time_since_last_failure": time.time() - self.last_failure_time if self.last_failure_time else 0
        }


def retry_with_backoff(
    config: RetryConfig = None,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """Decorator for retry with exponential backoff."""
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == config.max_attempts - 1:
                        # Last attempt, re-raise
                        logger.error(f"Function {func.__name__} failed after {config.max_attempts} attempts")
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** attempt),
                        config.max_delay
                    )
                    
                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        delay *= (0.5 + random.random() * 0.5)
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {delay:.2f}s")
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator


class ErrorHandler:
    """Centralized error handling and recovery."""
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.error_counts: Dict[str, int] = {}
        self._lock = threading.Lock()
    
    def get_circuit_breaker(self, name: str, config: CircuitBreakerConfig = None) -> CircuitBreaker:
        """Get or create circuit breaker for a service."""
        with self._lock:
            if name not in self.circuit_breakers:
                if config is None:
                    config = CircuitBreakerConfig()
                self.circuit_breakers[name] = CircuitBreaker(config)
            return self.circuit_breakers[name]
    
    def record_error(self, service: str, error: Exception):
        """Record an error for statistics."""
        with self._lock:
            self.error_counts[service] = self.error_counts.get(service, 0) + 1
        
        logger.error(f"Error in {service}: {error}")
    
    def get_error_stats(self) -> dict:
        """Get error statistics."""
        return {
            "error_counts": self.error_counts.copy(),
            "circuit_breakers": {
                name: breaker.get_state()
                for name, breaker in self.circuit_breakers.items()
            }
        }


# Global error handler instance
error_handler = ErrorHandler()


# Convenience decorators
def safe_database_operation(func: Callable) -> Callable:
    """Decorator for safe database operations."""
    import sqlite3
    
    config = RetryConfig(max_attempts=3, base_delay=0.5)
    circuit_config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=30.0,
        expected_exception=sqlite3.Error
    )
    
    circuit_breaker = error_handler.get_circuit_breaker("database", circuit_config)
    
    @circuit_breaker
    @retry_with_backoff(config, (sqlite3.Error,))
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as e:
            error_handler.record_error("database", e)
            raise
    
    return wrapper


def safe_ai_operation(func: Callable) -> Callable:
    """Decorator for safe AI operations."""
    config = RetryConfig(max_attempts=2, base_delay=2.0, max_delay=10.0)
    circuit_config = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout=60.0,
        expected_exception=Exception
    )
    
    circuit_breaker = error_handler.get_circuit_breaker("ai_service", circuit_config)
    
    @circuit_breaker
    @retry_with_backoff(config, (Exception,))
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_handler.record_error("ai_service", e)
            raise
    
    return wrapper


def safe_file_operation(func: Callable) -> Callable:
    """Decorator for safe file operations."""
    config = RetryConfig(max_attempts=2, base_delay=0.1)
    
    @retry_with_backoff(config, (OSError, IOError))
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (OSError, IOError) as e:
            error_handler.record_error("file_system", e)
            raise
    
    return wrapper


def timeout_operation(timeout_seconds: float):
    """Decorator to add timeout to operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import signal
            import threading
            
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Operation {func.__name__} timed out after {timeout_seconds}s")
            
            if threading.current_thread() is threading.main_thread():
                # Use signal for main thread
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(int(timeout_seconds))
                
                try:
                    result = func(*args, **kwargs)
                    signal.alarm(0)  # Cancel alarm
                    return result
                finally:
                    signal.signal(signal.SIGALRM, old_handler)
            else:
                # Use threading for other threads (signal doesn't work)
                result_container = []
                exception_container = []
                
                def target():
                    try:
                        result_container.append(func(*args, **kwargs))
                    except Exception as e:
                        exception_container.append(e)
                
                thread = threading.Thread(target=target)
                thread.daemon = True
                thread.start()
                thread.join(timeout_seconds)
                
                if thread.is_alive():
                    # Thread is still running, operation timed out
                    raise TimeoutError(f"Operation {func.__name__} timed out after {timeout_seconds}s")
                
                if exception_container:
                    raise exception_container[0]
                
                return result_container[0] if result_container else None
        
        return wrapper
    return decorator