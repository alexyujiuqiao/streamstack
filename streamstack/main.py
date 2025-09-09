"""
Main application entry point for StreamStack.

This module provides the main entry point for running the StreamStack
application server, handling command-line arguments and server startup.
"""

import sys
from typing import Optional

import uvicorn

from streamstack.core.app import create_app
from streamstack.core.config import get_settings
from streamstack.core.logging import configure_logging, get_logger


def main() -> None:
    """Main entry point for the StreamStack application."""
    settings = get_settings()
    
    # Configure logging early
    configure_logging(settings)
    logger = get_logger("main")
    
    logger.info(
        "Starting StreamStack",
        version=settings.version,
        provider=settings.provider,
        debug=settings.debug,
    )
    
    # Create the FastAPI application
    app = create_app(settings)
    
    # Configure uvicorn
    uvicorn_config = {
        "app": app,
        "host": settings.host,
        "port": settings.port,
        "workers": settings.workers if not settings.debug else 1,
        "log_config": None,  # We handle logging ourselves
        "access_log": False,  # We handle access logging in middleware
        "server_header": False,
        "date_header": False,
    }
    
    if settings.debug:
        uvicorn_config.update({
            "reload": True,
            "reload_dirs": ["streamstack"],
        })
    
    try:
        # Start the server
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal, stopping server")
    except Exception as e:
        logger.error("Server startup failed", error=str(e))
        sys.exit(1)


def create_app_for_testing(settings: Optional[object] = None):
    """Create application instance for testing."""
    return create_app(settings)


if __name__ == "__main__":
    main()