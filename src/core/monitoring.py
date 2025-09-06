"""Advanced monitoring and metrics collection system."""

import time
import threading
import psutil
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from collections import defaultdict, deque
import json

from loguru import logger


@dataclass
class MetricPoint:
    """A single metric measurement."""
    timestamp: float
    value: float
    labels: Dict[str, str] = None
    
    def __post_init__(self):
        if self.labels is None:
            self.labels = {}


@dataclass
class PerformanceMetrics:
    """System performance metrics."""
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_sent_mb: float
    network_recv_mb: float
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class ApplicationMetrics:
    """Application-specific metrics."""
    active_connections: int = 0
    cache_hit_rate: float = 0.0
    average_response_time: float = 0.0
    search_requests_per_minute: int = 0
    embedding_generation_time: float = 0.0
    database_query_time: float = 0.0
    error_rate: float = 0.0
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class MetricsCollector:
    """Collects and stores application metrics."""
    
    def __init__(self, retention_hours: int = 24, collection_interval: float = 5.0):
        self.retention_hours = retention_hours
        self.collection_interval = collection_interval
        
        # Thread-safe storage
        self._metrics = defaultdict(deque)
        self._counters = defaultdict(float)
        self._gauges = defaultdict(float)
        self._histograms = defaultdict(list)
        self._lock = threading.Lock()
        
        # Background collection
        self._running = False
        self._collection_thread = None
        
        # Performance tracking
        self._last_disk_io = None
        self._last_network_io = None
        
        # Application counters
        self.search_counter = 0
        self.embedding_counter = 0
        self.error_counter = 0
        
        # Response time tracking
        self.response_times = deque(maxlen=1000)
        self.cache_hits = 0
        self.cache_misses = 0
    
    def start_collection(self):
        """Start background metrics collection."""
        if not self._running:
            self._running = True
            self._collection_thread = threading.Thread(target=self._collect_loop, daemon=True)
            self._collection_thread.start()
            logger.info("Metrics collection started")
    
    def stop_collection(self):
        """Stop background metrics collection."""
        self._running = False
        if self._collection_thread:
            self._collection_thread.join(timeout=5.0)
        logger.info("Metrics collection stopped")
    
    def _collect_loop(self):
        """Background collection loop."""
        while self._running:
            try:
                self._collect_system_metrics()
                self._collect_application_metrics()
                self._cleanup_old_metrics()
                time.sleep(self.collection_interval)
            except Exception as e:
                logger.error(f"Error in metrics collection: {e}")
                time.sleep(self.collection_interval)
    
    def _collect_system_metrics(self):
        """Collect system performance metrics."""
        try:
            # CPU and Memory
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            
            # Disk I/O
            disk_io = psutil.disk_io_counters()
            disk_read_mb, disk_write_mb = 0.0, 0.0
            
            if disk_io and self._last_disk_io:
                disk_read_mb = (disk_io.read_bytes - self._last_disk_io.read_bytes) / (1024 * 1024)
                disk_write_mb = (disk_io.write_bytes - self._last_disk_io.write_bytes) / (1024 * 1024)
            
            self._last_disk_io = disk_io
            
            # Network I/O
            net_io = psutil.net_io_counters()
            net_sent_mb, net_recv_mb = 0.0, 0.0
            
            if net_io and self._last_network_io:
                net_sent_mb = (net_io.bytes_sent - self._last_network_io.bytes_sent) / (1024 * 1024)
                net_recv_mb = (net_io.bytes_recv - self._last_network_io.bytes_recv) / (1024 * 1024)
            
            self._last_network_io = net_io
            
            # Store metrics
            metrics = PerformanceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / (1024 * 1024),
                disk_io_read_mb=disk_read_mb,
                disk_io_write_mb=disk_write_mb,
                network_sent_mb=net_sent_mb,
                network_recv_mb=net_recv_mb
            )
            
            with self._lock:
                self._metrics['system'].append(metrics)
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    def _collect_application_metrics(self):
        """Collect application-specific metrics."""
        try:
            # Calculate rates and averages
            cache_hit_rate = 0.0
            if self.cache_hits + self.cache_misses > 0:
                cache_hit_rate = self.cache_hits / (self.cache_hits + self.cache_misses)
            
            avg_response_time = 0.0
            if self.response_times:
                avg_response_time = sum(self.response_times) / len(self.response_times)
            
            # Calculate error rate (errors per minute)
            error_rate = self.error_counter  # Reset after each collection
            self.error_counter = 0
            
            metrics = ApplicationMetrics(
                cache_hit_rate=cache_hit_rate,
                average_response_time=avg_response_time,
                search_requests_per_minute=self.search_counter,
                error_rate=error_rate
            )
            
            with self._lock:
                self._metrics['application'].append(metrics)
            
            # Reset counters
            self.search_counter = 0
            
        except Exception as e:
            logger.error(f"Error collecting application metrics: {e}")
    
    def _cleanup_old_metrics(self):
        """Remove metrics older than retention period."""
        cutoff_time = time.time() - (self.retention_hours * 3600)
        
        with self._lock:
            for metric_type, values in self._metrics.items():
                while values and values[0].timestamp < cutoff_time:
                    values.popleft()
    
    def record_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        """Record a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] += value
    
    def record_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value
    
    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a histogram metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._histograms[key].append(value)
            
            # Keep only last 1000 values
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]
    
    def record_search_request(self, response_time: float):
        """Record a search request with response time."""
        self.search_counter += 1
        self.response_times.append(response_time)
    
    def record_cache_hit(self):
        """Record a cache hit."""
        self.cache_hits += 1
    
    def record_cache_miss(self):
        """Record a cache miss."""
        self.cache_misses += 1
    
    def record_error(self):
        """Record an application error."""
        self.error_counter += 1
    
    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Create a unique key for metric storage."""
        if labels:
            label_str = ','.join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}[{label_str}]"
        return name
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current application metrics."""
        with self._lock:
            system_metrics = list(self._metrics['system'])[-1] if self._metrics['system'] else None
            app_metrics = list(self._metrics['application'])[-1] if self._metrics['application'] else None
            
            return {
                'system': asdict(system_metrics) if system_metrics else None,
                'application': asdict(app_metrics) if app_metrics else None,
                'counters': dict(self._counters),
                'gauges': dict(self._gauges),
                'timestamp': time.time()
            }
    
    def get_metrics_history(self, hours: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        """Get metrics history for the specified time period."""
        cutoff_time = time.time() - (hours * 3600)
        
        with self._lock:
            history = {}
            
            for metric_type, values in self._metrics.items():
                history[metric_type] = [
                    asdict(metric) for metric in values
                    if metric.timestamp >= cutoff_time
                ]
            
            return history
    
    def get_histogram_stats(self, name: str, labels: Dict[str, str] = None) -> Dict[str, float]:
        """Get statistics for a histogram metric."""
        key = self._make_key(name, labels)
        
        with self._lock:
            values = self._histograms.get(key, [])
            
            if not values:
                return {'count': 0, 'min': 0, 'max': 0, 'avg': 0, 'p50': 0, 'p95': 0, 'p99': 0}
            
            sorted_values = sorted(values)
            count = len(sorted_values)
            
            return {
                'count': count,
                'min': sorted_values[0],
                'max': sorted_values[-1],
                'avg': sum(sorted_values) / count,
                'p50': sorted_values[int(count * 0.5)],
                'p95': sorted_values[int(count * 0.95)] if count > 20 else sorted_values[-1],
                'p99': sorted_values[int(count * 0.99)] if count > 100 else sorted_values[-1]
            }


class HealthChecker:
    """Application health monitoring."""
    
    def __init__(self):
        self.checks = {}
        self._lock = threading.Lock()
    
    def register_check(self, name: str, check_func: Callable[[], bool], timeout: float = 5.0):
        """Register a health check."""
        with self._lock:
            self.checks[name] = {
                'func': check_func,
                'timeout': timeout,
                'last_result': None,
                'last_check': 0
            }
        
        logger.info(f"Registered health check: {name}")
    
    def run_checks(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {}
        overall_healthy = True
        
        with self._lock:
            checks_copy = dict(self.checks)
        
        for name, check_info in checks_copy.items():
            try:
                start_time = time.time()
                
                # Simple timeout mechanism
                result = check_info['func']()
                elapsed = time.time() - start_time
                
                if elapsed > check_info['timeout']:
                    result = False
                    error = f"Timeout after {elapsed:.2f}s"
                else:
                    error = None
                
                results[name] = {
                    'healthy': result,
                    'response_time': elapsed,
                    'error': error,
                    'timestamp': time.time()
                }
                
                with self._lock:
                    self.checks[name]['last_result'] = result
                    self.checks[name]['last_check'] = time.time()
                
                if not result:
                    overall_healthy = False
                    
            except Exception as e:
                results[name] = {
                    'healthy': False,
                    'error': str(e),
                    'timestamp': time.time()
                }
                overall_healthy = False
                logger.error(f"Health check {name} failed: {e}")
        
        results['overall'] = {'healthy': overall_healthy}
        return results
    
    def get_status(self) -> Dict[str, str]:
        """Get simple health status."""
        results = self.run_checks()
        return {
            'status': 'healthy' if results['overall']['healthy'] else 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'checks': {name: 'ok' if check['healthy'] else 'fail' 
                      for name, check in results.items() if name != 'overall'}
        }


# Global instances
metrics_collector = MetricsCollector()
health_checker = HealthChecker()


def timed_operation(metric_name: str = None):
    """Decorator to time operations and record metrics."""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                success = True
            except Exception as e:
                metrics_collector.record_error()
                success = False
                raise
            finally:
                elapsed = time.time() - start_time
                name = metric_name or func.__name__
                metrics_collector.record_histogram(f"{name}_duration", elapsed)
                
                if 'search' in name.lower():
                    metrics_collector.record_search_request(elapsed)
            
            return result
        return wrapper
    return decorator


def monitor_memory_usage():
    """Monitor memory usage and log warnings."""
    memory = psutil.virtual_memory()
    if memory.percent > 90:
        logger.warning(f"High memory usage: {memory.percent:.1f}%")
    elif memory.percent > 80:
        logger.info(f"Memory usage: {memory.percent:.1f}%")


def setup_default_health_checks():
    """Setup default health checks."""
    
    def check_database():
        """Check database connectivity."""
        try:
            from .database import DatabaseManager
            db = DatabaseManager()
            with db.get_connection() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except:
            return False
    
    def check_memory():
        """Check memory usage is below threshold."""
        return psutil.virtual_memory().percent < 95
    
    def check_disk_space():
        """Check disk space is available."""
        try:
            disk_usage = psutil.disk_usage('.')
            return (disk_usage.free / disk_usage.total) > 0.1  # 10% free space
        except:
            return False
    
    health_checker.register_check('database', check_database)
    health_checker.register_check('memory', check_memory) 
    health_checker.register_check('disk_space', check_disk_space)