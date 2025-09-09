"""
Basic unit tests for StreamStack core functionality.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from streamstack.core.config import Settings, ProviderType
from streamstack.providers.base import ChatCompletionRequest, ChatMessage
from streamstack.providers.openai_provider import OpenAIProvider


class TestSettings:
    """Test configuration management."""
    
    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        assert settings.app_name == "StreamStack"
        assert settings.version == "0.1.0"
        assert settings.provider == ProviderType.OPENAI
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
    
    def test_environment_override(self, monkeypatch):
        """Test environment variable override."""
        monkeypatch.setenv("STREAMSTACK_PORT", "9000")
        monkeypatch.setenv("STREAMSTACK_PROVIDER", "vllm")
        
        settings = Settings()
        assert settings.port == 9000
        assert settings.provider == ProviderType.VLLM
    
    def test_redis_config(self):
        """Test Redis configuration."""
        settings = Settings()
        config = settings.redis_config
        
        assert config["url"] == "redis://localhost:6379/0"
        assert config["max_connections"] == 100
        assert config["decode_responses"] is True


class TestChatCompletionRequest:
    """Test chat completion request model."""
    
    def test_valid_request(self):
        """Test valid chat completion request."""
        messages = [ChatMessage(role="user", content="Hello")]
        request = ChatCompletionRequest(
            model="gpt-3.5-turbo",
            messages=messages
        )
        
        assert request.model == "gpt-3.5-turbo"
        assert len(request.messages) == 1
        assert request.temperature == 0.7
        assert request.stream is False
    
    def test_invalid_temperature(self):
        """Test invalid temperature validation."""
        messages = [ChatMessage(role="user", content="Hello")]
        
        with pytest.raises(ValueError):
            ChatCompletionRequest(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=3.0  # Invalid: > 2.0
            )


class TestOpenAIProvider:
    """Test OpenAI provider implementation."""
    
    @pytest.fixture
    def provider_config(self):
        """Provider configuration fixture."""
        return {
            "api_key": "test-api-key",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-3.5-turbo",
            "timeout": 30,
        }
    
    @pytest.fixture
    def provider(self, provider_config):
        """OpenAI provider fixture."""
        return OpenAIProvider(provider_config)
    
    def test_provider_initialization(self, provider):
        """Test provider initialization."""
        assert provider.name == "openai"
        assert "gpt-3.5-turbo" in provider.supported_models
        assert "gpt-4" in provider.supported_models
    
    def test_missing_api_key(self):
        """Test initialization without API key."""
        with pytest.raises(ValueError, match="OpenAI API key is required"):
            OpenAIProvider({})
    
    def test_cost_estimation(self, provider):
        """Test cost estimation."""
        messages = [ChatMessage(role="user", content="Hello" * 100)]  # ~100 tokens
        request = ChatCompletionRequest(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=50
        )
        
        cost = provider.estimate_cost(request)
        assert cost > 0
        assert isinstance(cost, float)
    
    @pytest.mark.asyncio
    async def test_model_validation(self, provider):
        """Test model validation."""
        assert await provider.validate_model("gpt-3.5-turbo") is True
        assert await provider.validate_model("invalid-model") is False


if __name__ == "__main__":
    pytest.main([__file__])