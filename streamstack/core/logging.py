"""
Structured logging configuration for StreamStack.

This module sets up structured logging with correlation IDs, request tracking,
and JSON formatting for production environments.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

import structlog
from structlog.stdlib import LoggerFactory

from streamstack.core.config import Settings

# Context variables for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)


def add_correlation_id(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add correlation IDs to log entries."""
    request_id = request_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    
    user_id = user_id_var.get()
    if user_id:
        event_dict["user_id"] = user_id
    
    return event_dict


def add_severity_level(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add severity level for structured logging."""
    event_dict["severity"] = method_name.upper()
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structured logging based on settings."""
    
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.value),
        stream=sys.stdout,
        format="%(message)s",
    )
    
    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        add_severity_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]
    
    if settings.is_production:
        # Production: JSON output for log aggregation
        processors.extend([
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ])
    else:
        # Development: Pretty colored output
        processors.extend([
            structlog.dev.ConsoleRenderer(colors=True)
        ])
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.value)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


def set_request_id(request_id: Optional[str] = None) -> str:
    """Set request ID in context. Generate one if not provided."""
    if request_id is None:
        request_id = str(uuid.uuid4())
    request_id_var.set(request_id)
    return request_id


def set_user_id(user_id: str) -> None:
    """Set user ID in context."""
    user_id_var.set(user_id)


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_id_var.get()


def get_user_id() -> Optional[str]:
    """Get current user ID from context."""
    return user_id_var.get()


class LoggerMixin:
    """Mixin to add structured logging to classes."""
    
    @property
    def logger(self) -> structlog.BoundLogger:
        """Get logger for this class."""
        return get_logger(self.__class__.__name__)