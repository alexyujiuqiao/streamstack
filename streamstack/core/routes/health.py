"""
Health check endpoints for monitoring and load balancer integration.
"""

import asyncio
import time
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamstack.core.config import get_settings
from streamstack.core.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger("routes.health")


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: float
    version: str
    uptime: float
    checks: Dict[str, Any]


class LivenessResponse(BaseModel):
    """Liveness probe response model."""
    status: str
    timestamp: float


class ReadinessResponse(BaseModel):
    """Readiness probe response model."""
    status: str
    timestamp: float
    ready: bool
    checks: Dict[str, Any]


# Track application start time for uptime calculation
_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Comprehensive health check endpoint.
    
    Returns detailed health information including uptime, version,
    and status of critical dependencies.
    """
    settings = get_settings()
    current_time = time.time()
    uptime = current_time - _start_time
    
    checks = {}
    
    # Check Redis connectivity
    try:
        # TODO: Implement actual Redis health check
        checks["redis"] = {"status": "healthy", "latency_ms": 1.5}
    except Exception as e:
        logger.warning("Redis health check failed", error=str(e))
        checks["redis"] = {"status": "unhealthy", "error": str(e)}
    
    # Check LLM provider connectivity
    try:
        from streamstack.providers.manager import get_provider_manager
        provider_manager = get_provider_manager()
        provider_health = await provider_manager.get_health()
        checks["llm_provider"] = {
            "status": "healthy" if provider_health["healthy"] else "unhealthy",
            "provider": provider_health.get("provider", "unknown"),
            "latency_ms": provider_health.get("latency_ms"),
            "error": provider_health.get("error"),
        }
    except Exception as e:
        logger.warning("LLM provider health check failed", error=str(e))
        checks["llm_provider"] = {"status": "unhealthy", "error": str(e)}
    
    # Check queue status
    try:
        # TODO: Implement actual queue health check
        checks["queue"] = {"status": "healthy", "depth": 0, "max_size": settings.max_queue_size}
    except Exception as e:
        logger.warning("Queue health check failed", error=str(e))
        checks["queue"] = {"status": "unhealthy", "error": str(e)}
    
    # Determine overall status
    overall_status = "healthy"
    for check in checks.values():
        if check["status"] != "healthy":
            overall_status = "degraded"
            break
    
    return HealthResponse(
        status=overall_status,
        timestamp=current_time,
        version=settings.version,
        uptime=uptime,
        checks=checks
    )


@router.get("/health/live", response_model=LivenessResponse)
async def liveness_check() -> LivenessResponse:
    """
    Kubernetes liveness probe endpoint.
    
    Returns basic status to indicate the application is running.
    This should only fail if the application is completely broken.
    """
    return LivenessResponse(
        status="alive",
        timestamp=time.time()
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    """
    Kubernetes readiness probe endpoint.
    
    Returns status indicating whether the application is ready to serve traffic.
    This can fail if dependencies are unavailable.
    """
    settings = get_settings()
    current_time = time.time()
    checks = {}
    ready = True
    
    # Check critical dependencies for readiness
    try:
        # TODO: Quick Redis connectivity check
        checks["redis"] = "ready"
    except Exception as e:
        logger.warning("Redis readiness check failed", error=str(e))
        checks["redis"] = "not_ready"
        ready = False
    
    try:
        from streamstack.providers.manager import get_provider_manager
        provider_manager = get_provider_manager()
        provider_health = await provider_manager.get_health()
        checks["llm_provider"] = "ready" if provider_health["healthy"] else "not_ready"
        if not provider_health["healthy"]:
            ready = False
    except Exception as e:
        logger.warning("LLM provider readiness check failed", error=str(e))
        checks["llm_provider"] = "not_ready"
        ready = False
    
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not ready"
        )
    
    return ReadinessResponse(
        status="ready",
        timestamp=current_time,
        ready=ready,
        checks=checks
    )