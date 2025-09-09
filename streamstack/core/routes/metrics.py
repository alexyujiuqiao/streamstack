"""
Prometheus metrics endpoint for monitoring and alerting.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from streamstack.core.logging import get_logger
from streamstack.observability.metrics import get_registry

router = APIRouter(tags=["metrics"])
logger = get_logger("routes.metrics")


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    """
    Prometheus metrics endpoint.
    
    Returns all collected metrics in Prometheus format for scraping.
    """
    try:
        registry = get_registry()
        metrics_data = generate_latest(registry)
        
        return PlainTextResponse(
            content=metrics_data.decode('utf-8'),
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.error("Failed to generate metrics", error=str(e))
        return PlainTextResponse(
            content="# Failed to generate metrics\n",
            status_code=500
        )