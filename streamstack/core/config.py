"""
Configuration management for StreamStack.

This module handles all configuration through environment variables and Pydantic settings,
providing type safety and validation for all configuration options.
"""

import os
from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, Enum):
    """Available log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ProviderType(str, Enum):
    """Available LLM provider types."""
    OPENAI = "openai"
    VLLM = "vllm"
    CUSTOM = "custom"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_prefix="STREAMSTACK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application settings
    app_name: str = Field(default="StreamStack", description="Application name")
    version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")
    
    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=1, description="Number of worker processes")
    
    # LLM Provider settings
    provider: ProviderType = Field(default=ProviderType.OPENAI, description="LLM provider type")
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY", description="OpenAI API key")
    openai_base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI base URL")
    openai_model: str = Field(default="gpt-3.5-turbo", description="Default OpenAI model")
    
    # vLLM settings
    vllm_base_url: str = Field(default="http://localhost:8001", description="vLLM server base URL")
    vllm_model: str = Field(default="meta-llama/Llama-2-7b-chat-hf", description="Default vLLM model")
    
    # Redis settings
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_max_connections: int = Field(default=100, description="Maximum Redis connections")
    
    # Queue settings
    max_queue_size: int = Field(default=1000, description="Maximum queue size")
    request_timeout: int = Field(default=300, description="Request timeout in seconds")
    queue_check_interval: float = Field(default=0.1, description="Queue check interval in seconds")
    
    # Rate limiting settings
    rate_limit_requests_per_minute: int = Field(default=100, description="Requests per minute limit")
    rate_limit_tokens_per_minute: int = Field(default=10000, description="Tokens per minute limit")
    rate_limit_burst_size: int = Field(default=10, description="Burst size for token bucket")
    
    # Observability settings
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    enable_tracing: bool = Field(default=True, description="Enable OpenTelemetry tracing")
    jaeger_endpoint: str = Field(default="http://localhost:14268/api/traces", description="Jaeger endpoint")
    metrics_path: str = Field(default="/metrics", description="Metrics endpoint path")
    
    # Health check settings
    health_check_timeout: int = Field(default=30, description="Health check timeout in seconds")
    
    # Security settings
    enable_cors: bool = Field(default=True, description="Enable CORS")
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return not self.debug and self.log_level != LogLevel.DEBUG
    
    @property
    def redis_config(self) -> dict:
        """Get Redis configuration dictionary."""
        return {
            "url": self.redis_url,
            "max_connections": self.redis_max_connections,
            "decode_responses": True,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry_on_timeout": True,
        }


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the application settings."""
    return settings