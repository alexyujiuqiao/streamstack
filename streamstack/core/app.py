"""
Core FastAPI application factory and setup.

This module creates and configures the FastAPI application with all middleware,
routes, and dependencies required for production operation.
"""

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from streamstack.core.config import Settings, get_settings
from streamstack.core.logging import configure_logging, get_logger, set_request_id
from streamstack.core.routes import setup_routes
from streamstack.observability.metrics import setup_metrics
from streamstack.observability.tracing import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()
    logger = get_logger("app.lifespan")
    
    logger.info("Starting StreamStack application", version=settings.version)
    
    # Initialize observability
    if settings.enable_metrics:
        setup_metrics()
        logger.info("Metrics collection enabled")
    
    if settings.enable_tracing:
        setup_tracing(settings)
        logger.info("Distributed tracing enabled")
    
    # Initialize provider manager
    try:
        from streamstack.providers.manager import get_provider_manager
        provider_manager = get_provider_manager()
        await provider_manager.initialize(settings)
        logger.info("Provider manager initialized")
    except Exception as e:
        logger.error("Failed to initialize provider manager", error=str(e))
        raise
    
    # Initialize queue manager
    try:
        from streamstack.queue.manager import get_queue_manager
        queue_manager = get_queue_manager()
        await queue_manager.initialize(settings)
        logger.info("Queue manager initialized")
    except Exception as e:
        logger.error("Failed to initialize queue manager", error=str(e))
        raise
    
    # Initialize rate limit manager
    try:
        from streamstack.queue.rate_limiter import get_rate_limit_manager
        rate_limit_manager = get_rate_limit_manager()
        await rate_limit_manager.initialize(settings)
        logger.info("Rate limit manager initialized")
    except Exception as e:
        logger.error("Failed to initialize rate limit manager", error=str(e))
        raise
    
    logger.info("Application startup complete")
    
    yield
    
    logger.info("Shutting down StreamStack application")
    
    # Cleanup provider manager
    try:
        from streamstack.providers.manager import get_provider_manager
        provider_manager = get_provider_manager()
        await provider_manager.close()
        logger.info("Provider manager closed")
    except Exception as e:
        logger.warning("Error closing provider manager", error=str(e))
    
    # Cleanup queue manager
    try:
        from streamstack.queue.manager import get_queue_manager
        queue_manager = get_queue_manager()
        await queue_manager.close()
        logger.info("Queue manager closed")
    except Exception as e:
        logger.warning("Error closing queue manager", error=str(e))
    
    # Cleanup rate limit manager
    try:
        from streamstack.queue.rate_limiter import get_rate_limit_manager
        rate_limit_manager = get_rate_limit_manager()
        await rate_limit_manager.close()
        logger.info("Rate limit manager closed")
    except Exception as e:
        logger.warning("Error closing rate limit manager", error=str(e))
    
    logger.info("Application shutdown complete")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()
    
    # Configure logging first
    configure_logging(settings)
    logger = get_logger("app.factory")
    
    logger.info("Creating FastAPI application", config=settings.dict())
    
    # Create FastAPI app
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Production-grade LLM serving platform",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    if settings.enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    # Add request tracking middleware
    @app.middleware("http")
    async def add_request_tracking(request: Request, call_next):
        """Add request tracking and timing."""
        # Set request ID
        request_id = request.headers.get("X-Request-ID") or set_request_id()
        
        # Track request start time
        start_time = time.time()
        
        logger = get_logger("app.request")
        logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            user_agent=request.headers.get("User-Agent"),
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            # Log successful request
            duration = time.time() - start_time
            logger.info(
                "Request completed",
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
            )
            
            return response
            
        except Exception as exc:
            # Log failed request
            duration = time.time() - start_time
            logger.error(
                "Request failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=round(duration * 1000, 2),
            )
            
            # Return error response
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
    
    # Setup routes
    setup_routes(app, settings)
    
    logger.info("FastAPI application created successfully")
    return app