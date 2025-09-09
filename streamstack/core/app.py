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
    
    # TODO: Initialize Redis connection pool
    # TODO: Initialize LLM providers
    # TODO: Initialize rate limiters
    
    logger.info("Application startup complete")
    
    yield
    
    logger.info("Shutting down StreamStack application")
    
    # TODO: Cleanup Redis connections
    # TODO: Cleanup LLM provider connections
    
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