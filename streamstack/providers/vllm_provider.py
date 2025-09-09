"""
vLLM provider implementation.

This module implements the LLM provider interface for vLLM server,
providing a local alternative to OpenAI with OpenAI-compatible API.
"""

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from pydantic import ValidationError

from streamstack.core.logging import get_logger
from streamstack.providers.base import (
    BaseLLMProvider,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderError,
    ProviderHealth,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderUsage,
)

logger = get_logger("providers.vllm")


class VLLMProvider(BaseLLMProvider):
    """vLLM LLM provider implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize vLLM provider."""
        super().__init__(config)
        
        self.base_url = config.get("base_url", "http://localhost:8001")
        self.default_model = config.get("default_model", "meta-llama/Llama-2-7b-chat-hf")
        self.timeout = config.get("timeout", 120)  # vLLM can be slower
        self.max_retries = config.get("max_retries", 3)
        
        # Initialize HTTP client
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        
        # Usage tracking
        self._requests_count = 0
        self._tokens_consumed = 0
        self._total_latency = 0.0
        self._available_models: List[str] = []
        
        logger.info("vLLM provider initialized", base_url=self.base_url)
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "vllm"
    
    @property
    def supported_models(self) -> List[str]:
        """List of supported model names."""
        return self._available_models or [self.default_model]
    
    async def chat_completion(
        self,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Create a chat completion."""
        start_time = time.time()
        
        try:
            # Prepare request payload
            payload = self._prepare_request_payload(request)
            
            logger.info(
                "Sending chat completion request to vLLM",
                model=request.model,
                message_count=len(request.messages),
                stream=request.stream,
            )
            
            # Make API request
            response = await self._make_request("POST", "/v1/chat/completions", payload)
            
            # Parse response
            completion_response = ChatCompletionResponse(**response)
            
            # Track usage
            latency = time.time() - start_time
            self._track_usage(completion_response, latency)
            
            logger.info(
                "vLLM chat completion successful",
                completion_id=completion_response.id,
                model=completion_response.model,
                prompt_tokens=completion_response.usage.prompt_tokens,
                completion_tokens=completion_response.usage.completion_tokens,
                latency_ms=round(latency * 1000, 2),
            )
            
            return completion_response
            
        except Exception as e:
            latency = time.time() - start_time
            logger.error(
                "vLLM chat completion failed",
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=round(latency * 1000, 2),
            )
            raise self._handle_error(e)
    
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Create a streaming chat completion."""
        start_time = time.time()
        
        try:
            # Prepare request payload for streaming
            payload = self._prepare_request_payload(request)
            payload["stream"] = True
            
            logger.info(
                "Starting streaming chat completion with vLLM",
                model=request.model,
                message_count=len(request.messages),
            )
            
            # Make streaming API request
            async with self._client.stream("POST", "/v1/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ProviderError(f"vLLM API request failed: {error_text.decode()}")
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix
                        
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk_data = json.loads(data)
                            chunk = ChatCompletionChunk(**chunk_data)
                            yield chunk
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse vLLM streaming chunk", data=data)
                            continue
                        except ValidationError as e:
                            logger.warning("Invalid vLLM chunk format", error=str(e))
                            continue
            
            # Track usage (estimate for streaming)
            latency = time.time() - start_time
            self._requests_count += 1
            self._total_latency += latency
            
            logger.info(
                "vLLM streaming chat completion completed",
                latency_ms=round(latency * 1000, 2),
            )
            
        except Exception as e:
            latency = time.time() - start_time
            logger.error(
                "vLLM streaming chat completion failed",
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=round(latency * 1000, 2),
            )
            raise self._handle_error(e)
    
    async def health_check(self) -> ProviderHealth:
        """Check provider health."""
        start_time = time.time()
        
        try:
            # Check if vLLM server is running
            response = await self._make_request("GET", "/v1/models")
            latency = time.time() - start_time
            
            # Update available models
            models_data = response.get("data", [])
            self._available_models = [model["id"] for model in models_data]
            
            return ProviderHealth(
                healthy=True,
                latency_ms=round(latency * 1000, 2),
                metadata={
                    "models_available": len(models_data),
                    "server_type": "vllm",
                    "api_version": "v1",
                }
            )
        except Exception as e:
            latency = time.time() - start_time
            return ProviderHealth(
                healthy=False,
                latency_ms=round(latency * 1000, 2),
                error=str(e),
            )
    
    async def get_usage_stats(self) -> ProviderUsage:
        """Get provider usage statistics."""
        avg_latency = (
            self._total_latency / self._requests_count
            if self._requests_count > 0
            else 0.0
        )
        
        return ProviderUsage(
            requests_count=self._requests_count,
            tokens_consumed=self._tokens_consumed,
            cost_usd=0.0,  # vLLM is free/local
            avg_latency_ms=round(avg_latency * 1000, 2),
        )
    
    def estimate_cost(self, request: ChatCompletionRequest) -> float:
        """Estimate the cost of a request in USD."""
        # vLLM is typically free for local/self-hosted deployments
        return 0.0
    
    async def validate_model(self, model: str) -> bool:
        """Validate if a model is supported."""
        # Refresh available models if needed
        if not self._available_models:
            try:
                await self.health_check()
            except Exception:
                pass
        
        return model in self.supported_models
    
    def _prepare_request_payload(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Prepare request payload for vLLM API."""
        payload = {
            "model": request.model,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    **({"name": msg.name} if msg.name else {})
                }
                for msg in request.messages
            ],
        }
        
        # Add optional parameters (vLLM supports most OpenAI parameters)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.frequency_penalty is not None:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            payload["presence_penalty"] = request.presence_penalty
        if request.stop:
            payload["stop"] = request.stop
        if request.user:
            payload["user"] = request.user
        
        return payload
    
    async def _make_request(self, method: str, endpoint: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        """Make an HTTP request to the vLLM API."""
        for attempt in range(self.max_retries + 1):
            try:
                if method == "GET":
                    response = await self._client.get(endpoint)
                else:
                    response = await self._client.post(endpoint, json=payload)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 503:
                    # vLLM server might be starting up or overloaded
                    raise ProviderUnavailableError(
                        "vLLM server unavailable",
                        retry_after=30
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_message = error_data.get("detail", f"HTTP {response.status_code}")
                    raise ProviderError(error_message, status_code=response.status_code)
                    
            except httpx.TimeoutException:
                if attempt == self.max_retries:
                    raise ProviderTimeoutError("vLLM request timeout")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except httpx.ConnectError:
                if attempt == self.max_retries:
                    raise ProviderUnavailableError("Cannot connect to vLLM server")
                await asyncio.sleep(2 ** attempt)
            except (ProviderError, ProviderUnavailableError):
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise ProviderError(f"Unexpected vLLM error: {str(e)}")
                await asyncio.sleep(2 ** attempt)
    
    def _handle_error(self, error: Exception) -> ProviderError:
        """Convert exceptions to appropriate provider errors."""
        if isinstance(error, ProviderError):
            return error
        elif isinstance(error, httpx.TimeoutException):
            return ProviderTimeoutError("vLLM request timeout")
        elif isinstance(error, httpx.ConnectError):
            return ProviderUnavailableError("Cannot connect to vLLM server")
        else:
            return ProviderError(f"Unexpected vLLM error: {str(error)}")
    
    def _track_usage(self, response: ChatCompletionResponse, latency: float) -> None:
        """Track usage statistics."""
        self._requests_count += 1
        self._tokens_consumed += response.usage.total_tokens
        self._total_latency += latency
    
    async def close(self) -> None:
        """Close the provider and cleanup resources."""
        await self._client.aclose()
        logger.info("vLLM provider closed")