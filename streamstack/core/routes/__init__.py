"""
API routes setup for StreamStack.

This module defines and configures all API endpoints including chat completions,
health checks, and metrics endpoints.
"""

from fastapi import FastAPI

from streamstack.core.config import Settings
from streamstack.core.logging import get_logger


def setup_routes(app: FastAPI, settings: Settings) -> None:
    """Setup all application routes."""
    logger = get_logger("app.routes")
    
    # Import route modules
    from streamstack.core.routes.chat import router as chat_router
    from streamstack.core.routes.health import router as health_router
    from streamstack.core.routes.metrics import router as metrics_router
    
    # Include routers
    app.include_router(chat_router, prefix="/v1")
    app.include_router(health_router)
    app.include_router(metrics_router)
    
    logger.info("All routes configured successfully")