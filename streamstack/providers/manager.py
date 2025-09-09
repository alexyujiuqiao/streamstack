"""
Provider factory and management for LLM providers.

This module provides a factory for creating and managing LLM providers,
enabling dynamic provider selection and configuration.
"""

from typing import Dict, Any, Optional

from streamstack.core.config import ProviderType, Settings
from streamstack.core.logging import get_logger
from streamstack.providers.base import BaseLLMProvider
from streamstack.providers.openai_provider import OpenAIProvider
from streamstack.providers.vllm_provider import VLLMProvider

logger = get_logger("providers.factory")


class ProviderFactory:
    """Factory for creating LLM providers."""
    
    _providers = {
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.VLLM: VLLMProvider,
    }
    
    @classmethod
    def create_provider(
        cls,
        provider_type: ProviderType,
        config: Dict[str, Any]
    ) -> BaseLLMProvider:
        """
        Create a provider instance.
        
        Args:
            provider_type: Type of provider to create
            config: Provider configuration
            
        Returns:
            Provider instance
            
        Raises:
            ValueError: If provider type is not supported
        """
        if provider_type not in cls._providers:
            raise ValueError(f"Unsupported provider type: {provider_type}")
        
        provider_class = cls._providers[provider_type]
        
        logger.info(
            "Creating provider",
            provider_type=provider_type,
            provider_class=provider_class.__name__,
        )
        
        return provider_class(config)
    
    @classmethod
    def create_from_settings(cls, settings: Settings) -> BaseLLMProvider:
        """
        Create a provider from application settings.
        
        Args:
            settings: Application settings
            
        Returns:
            Provider instance
        """
        if settings.provider == ProviderType.OPENAI:
            config = {
                "api_key": settings.openai_api_key,
                "base_url": settings.openai_base_url,
                "default_model": settings.openai_model,
                "timeout": 60,
                "max_retries": 3,
            }
        elif settings.provider == ProviderType.VLLM:
            config = {
                "base_url": settings.vllm_base_url,
                "default_model": settings.vllm_model,
                "timeout": 120,
                "max_retries": 3,
            }
        else:
            raise ValueError(f"Unsupported provider: {settings.provider}")
        
        return cls.create_provider(settings.provider, config)
    
    @classmethod
    def register_provider(
        cls,
        provider_type: str,
        provider_class: type
    ) -> None:
        """
        Register a custom provider.
        
        Args:
            provider_type: Provider type identifier
            provider_class: Provider class
        """
        if not issubclass(provider_class, BaseLLMProvider):
            raise ValueError("Provider class must inherit from BaseLLMProvider")
        
        cls._providers[provider_type] = provider_class
        logger.info(
            "Custom provider registered",
            provider_type=provider_type,
            provider_class=provider_class.__name__,
        )


class ProviderManager:
    """Manager for LLM provider instances."""
    
    def __init__(self):
        self._provider: Optional[BaseLLMProvider] = None
        self._settings: Optional[Settings] = None
    
    async def initialize(self, settings: Settings) -> None:
        """
        Initialize the provider manager.
        
        Args:
            settings: Application settings
        """
        self._settings = settings
        
        try:
            self._provider = ProviderFactory.create_from_settings(settings)
            
            # Test provider health
            health = await self._provider.health_check()
            if not health.healthy:
                logger.warning(
                    "Provider health check failed",
                    provider=self._provider.name,
                    error=health.error,
                )
            else:
                logger.info(
                    "Provider initialized successfully",
                    provider=self._provider.name,
                    latency_ms=health.latency_ms,
                )
                
        except Exception as e:
            logger.error(
                "Failed to initialize provider",
                provider_type=settings.provider,
                error=str(e),
            )
            raise
    
    def get_provider(self) -> BaseLLMProvider:
        """
        Get the current provider instance.
        
        Returns:
            Provider instance
            
        Raises:
            RuntimeError: If provider is not initialized
        """
        if self._provider is None:
            raise RuntimeError("Provider not initialized")
        return self._provider
    
    async def switch_provider(
        self,
        provider_type: ProviderType,
        config: Dict[str, Any]
    ) -> None:
        """
        Switch to a different provider.
        
        Args:
            provider_type: New provider type
            config: Provider configuration
        """
        # Close current provider
        if self._provider:
            if hasattr(self._provider, 'close'):
                await self._provider.close()
        
        # Create new provider
        self._provider = ProviderFactory.create_provider(provider_type, config)
        
        # Test new provider
        health = await self._provider.health_check()
        if not health.healthy:
            logger.warning(
                "New provider health check failed",
                provider=self._provider.name,
                error=health.error,
            )
        
        logger.info(
            "Switched to new provider",
            provider=self._provider.name,
            provider_type=provider_type,
        )
    
    async def get_health(self) -> Dict[str, Any]:
        """
        Get provider health information.
        
        Returns:
            Health information dictionary
        """
        if not self._provider:
            return {"healthy": False, "error": "Provider not initialized"}
        
        try:
            health = await self._provider.health_check()
            return {
                "healthy": health.healthy,
                "provider": self._provider.name,
                "latency_ms": health.latency_ms,
                "error": health.error,
                "metadata": health.metadata,
            }
        except Exception as e:
            logger.error("Provider health check failed", error=str(e))
            return {
                "healthy": False,
                "provider": self._provider.name,
                "error": str(e),
            }
    
    async def get_usage_stats(self) -> Dict[str, Any]:
        """
        Get provider usage statistics.
        
        Returns:
            Usage statistics dictionary
        """
        if not self._provider:
            return {}
        
        try:
            usage = await self._provider.get_usage_stats()
            return {
                "provider": self._provider.name,
                "requests_count": usage.requests_count,
                "tokens_consumed": usage.tokens_consumed,
                "cost_usd": usage.cost_usd,
                "avg_latency_ms": usage.avg_latency_ms,
            }
        except Exception as e:
            logger.error("Failed to get usage stats", error=str(e))
            return {"provider": self._provider.name, "error": str(e)}
    
    async def close(self) -> None:
        """Close the provider manager and cleanup resources."""
        if self._provider and hasattr(self._provider, 'close'):
            await self._provider.close()
        self._provider = None
        logger.info("Provider manager closed")


# Global provider manager instance
provider_manager = ProviderManager()


def get_provider_manager() -> ProviderManager:
    """Get the global provider manager instance."""
    return provider_manager