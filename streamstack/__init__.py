# StreamStack Package
"""
Production-grade LLM serving platform with FastAPI.

This package provides a comprehensive solution for serving Large Language Models
with enterprise-grade features including rate limiting, queueing, observability,
and pluggable provider support.
"""

__version__ = "0.1.0"
__author__ = "StreamStack Team"
__description__ = "Production-grade LLM serving platform with FastAPI"

from streamstack.core.app import create_app
from streamstack.core.config import Settings

__all__ = ["create_app", "Settings"]