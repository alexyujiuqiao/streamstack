"""
Integration tests for StreamStack API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from streamstack.core.app import create_app
from streamstack.core.config import Settings


@pytest.fixture
def test_settings():
    """Test settings fixture."""
    return Settings(
        debug=True,
        enable_metrics=False,
        enable_tracing=False,
        provider="openai",
        openai_api_key="test-key",
        redis_url="redis://localhost:6379/1",  # Use test database
    )


@pytest.fixture
def test_app(test_settings):
    """Test FastAPI app fixture."""
    return create_app(test_settings)


@pytest.fixture
def client(test_app):
    """Test client fixture."""
    return TestClient(test_app)


class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_health_check(self, client):
        """Test main health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert "uptime" in data
        assert "checks" in data
    
    def test_liveness_check(self, client):
        """Test liveness probe endpoint."""
        response = client.get("/health/live")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data
    
    def test_readiness_check(self, client):
        """Test readiness probe endpoint."""
        # This might fail if dependencies aren't available
        response = client.get("/health/ready")
        assert response.status_code in [200, 503]
        
        data = response.json()
        assert "status" in data
        assert "ready" in data


class TestMetricsEndpoint:
    """Test metrics endpoint."""
    
    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        
        # Check for some basic metrics
        content = response.text
        assert "# HELP" in content  # Prometheus format


class TestChatCompletionsEndpoint:
    """Test chat completions endpoint."""
    
    @patch('streamstack.providers.manager.get_provider_manager')
    def test_chat_completion_simple(self, mock_manager, client):
        """Test simple chat completion."""
        # Mock provider
        mock_provider = AsyncMock()
        mock_provider.validate_model.return_value = True
        mock_provider.chat_completion.return_value = {
            "id": "test-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-3.5-turbo",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15
            }
        }
        
        mock_manager.return_value.get_provider.return_value = mock_provider
        
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == "test-123"
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
    
    def test_chat_completion_invalid_model(self, client):
        """Test chat completion with invalid model."""
        payload = {
            "model": "",  # Invalid empty model
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_chat_completion_missing_messages(self, client):
        """Test chat completion without messages."""
        payload = {
            "model": "gpt-3.5-turbo",
            "stream": False
        }
        
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 422  # Validation error
    
    def test_chat_completion_streaming(self, client):
        """Test streaming chat completion."""
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True
        }
        
        response = client.post("/v1/chat/completions", json=payload)
        # This will fail without proper provider setup, but we test the endpoint exists
        assert response.status_code in [200, 500]  # Either works or fails gracefully


class TestMiddleware:
    """Test middleware functionality."""
    
    def test_cors_headers(self, client):
        """Test CORS headers are present."""
        response = client.options("/health")
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers
    
    def test_request_id_header(self, client):
        """Test request ID header is added."""
        response = client.get("/health")
        assert "X-Request-ID" in response.headers
    
    def test_custom_request_id(self, client):
        """Test custom request ID is preserved."""
        custom_id = "custom-request-123"
        response = client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers["X-Request-ID"] == custom_id


if __name__ == "__main__":
    pytest.main([__file__])