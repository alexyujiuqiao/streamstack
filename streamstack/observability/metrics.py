"""
Prometheus metrics collection for StreamStack.

This module provides comprehensive metrics collection including latency histograms,
counters, gauges, and business metrics like token usage and costs.
"""

import time
from typing import Dict, Optional

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    start_http_server,
)

from streamstack.core.logging import get_logger

logger = get_logger("observability.metrics")

# Global registry for all metrics
_registry: Optional[CollectorRegistry] = None


def get_registry() -> CollectorRegistry:
    """Get the global metrics registry."""
    global _registry
    if _registry is None:
        _registry = REGISTRY
    return _registry


def setup_metrics() -> None:
    """Initialize all metrics collectors."""
    global _registry
    _registry = REGISTRY
    
    logger.info("Setting up Prometheus metrics")
    
    # Initialize all metric collectors
    get_request_counter()
    get_request_duration_histogram()
    get_active_requests_gauge()
    get_queue_depth_gauge()
    get_token_counter()
    get_cost_counter()
    get_provider_request_counter()
    get_error_counter()
    
    logger.info("Prometheus metrics setup complete")


# Request metrics
_request_counter: Optional[Counter] = None
_request_duration_histogram: Optional[Histogram] = None
_active_requests_gauge: Optional[Gauge] = None

def get_request_counter() -> Counter:
    """Get HTTP request counter."""
    global _request_counter
    if _request_counter is None:
        _request_counter = Counter(
            "streamstack_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=get_registry()
        )
    return _request_counter


def get_request_duration_histogram() -> Histogram:
    """Get HTTP request duration histogram."""
    global _request_duration_histogram
    if _request_duration_histogram is None:
        _request_duration_histogram = Histogram(
            "streamstack_http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=get_registry()
        )
    return _request_duration_histogram


def get_active_requests_gauge() -> Gauge:
    """Get active requests gauge."""
    global _active_requests_gauge
    if _active_requests_gauge is None:
        _active_requests_gauge = Gauge(
            "streamstack_active_requests",
            "Number of active HTTP requests",
            registry=get_registry()
        )
    return _active_requests_gauge


# Queue metrics
_queue_depth_gauge: Optional[Gauge] = None

def get_queue_depth_gauge() -> Gauge:
    """Get queue depth gauge."""
    global _queue_depth_gauge
    if _queue_depth_gauge is None:
        _queue_depth_gauge = Gauge(
            "streamstack_queue_depth",
            "Current queue depth",
            ["queue_type"],
            registry=get_registry()
        )
    return _queue_depth_gauge


# Token and cost metrics
_token_counter: Optional[Counter] = None
_cost_counter: Optional[Counter] = None

def get_token_counter() -> Counter:
    """Get token usage counter."""
    global _token_counter
    if _token_counter is None:
        _token_counter = Counter(
            "streamstack_tokens_total",
            "Total tokens processed",
            ["provider", "model", "token_type"],
            registry=get_registry()
        )
    return _token_counter


def get_cost_counter() -> Counter:
    """Get cost tracking counter."""
    global _cost_counter
    if _cost_counter is None:
        _cost_counter = Counter(
            "streamstack_cost_usd_total",
            "Total cost in USD",
            ["provider", "model"],
            registry=get_registry()
        )
    return _cost_counter


# Provider metrics
_provider_request_counter: Optional[Counter] = None

def get_provider_request_counter() -> Counter:
    """Get provider request counter."""
    global _provider_request_counter
    if _provider_request_counter is None:
        _provider_request_counter = Counter(
            "streamstack_provider_requests_total",
            "Total requests to LLM providers",
            ["provider", "model", "status"],
            registry=get_registry()
        )
    return _provider_request_counter


# Error metrics
_error_counter: Optional[Counter] = None

def get_error_counter() -> Counter:
    """Get error counter."""
    global _error_counter
    if _error_counter is None:
        _error_counter = Counter(
            "streamstack_errors_total",
            "Total errors",
            ["error_type", "component"],
            registry=get_registry()
        )
    return _error_counter


class MetricsCollector:
    """Context manager for collecting request metrics."""
    
    def __init__(self, method: str, endpoint: str):
        self.method = method
        self.endpoint = endpoint
        self.start_time = time.time()
        
        # Increment active requests
        get_active_requests_gauge().inc()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Record request duration
        duration = time.time() - self.start_time
        get_request_duration_histogram().labels(
            method=self.method,
            endpoint=self.endpoint
        ).observe(duration)
        
        # Record request count
        status_code = "500" if exc_type else "200"
        get_request_counter().labels(
            method=self.method,
            endpoint=self.endpoint,
            status_code=status_code
        ).inc()
        
        # Record error if occurred
        if exc_type:
            get_error_counter().labels(
                error_type=exc_type.__name__,
                component="api"
            ).inc()
        
        # Decrement active requests
        get_active_requests_gauge().dec()


def record_token_usage(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float = 0.0
) -> None:
    """Record token usage and cost metrics."""
    token_counter = get_token_counter()
    
    # Record token usage
    token_counter.labels(
        provider=provider,
        model=model,
        token_type="prompt"
    ).inc(prompt_tokens)
    
    token_counter.labels(
        provider=provider,
        model=model,
        token_type="completion"
    ).inc(completion_tokens)
    
    # Record cost if provided
    if cost_usd > 0:
        get_cost_counter().labels(
            provider=provider,
            model=model
        ).inc(cost_usd)


def record_provider_request(provider: str, model: str, status: str) -> None:
    """Record a request to an LLM provider."""
    get_provider_request_counter().labels(
        provider=provider,
        model=model,
        status=status
    ).inc()


def update_queue_depth(queue_type: str, depth: int) -> None:
    """Update queue depth metric."""
    get_queue_depth_gauge().labels(queue_type=queue_type).set(depth)


def record_error(error_type: str, component: str) -> None:
    """Record an error occurrence."""
    get_error_counter().labels(
        error_type=error_type,
        component=component
    ).inc()