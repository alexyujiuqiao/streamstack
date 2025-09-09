"""
OpenAI provider implementation.

This module implements the LLM provider interface for OpenAI's API,
supporting both GPT-3.5 and GPT-4 models with streaming capabilities.
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
    ChatMessage,
    ProviderError,
    ProviderHealth,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUsage,
)

logger = get_logger("providers.openai")


class OpenAIProvider(BaseLLMProvider):
    """OpenAI LLM provider implementation."""
    
    # Model pricing per 1K tokens (input, output) in USD
    MODEL_PRICING = {
        "gpt-3.5-turbo": (0.0015, 0.002),
        "gpt-3.5-turbo-16k": (0.003, 0.004),
        "gpt-4": (0.03, 0.06),
        "gpt-4-32k": (0.06, 0.12),
        "gpt-4-turbo-preview": (0.01, 0.03),
        "gpt-4-vision-preview": (0.01, 0.03),
    }
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize OpenAI provider."""
        super().__init__(config)
        
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
        
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.default_model = config.get("default_model", "gpt-3.5-turbo")
        self.timeout = config.get("timeout", 60)
        self.max_retries = config.get("max_retries", 3)
        
        # Initialize HTTP client
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        
        # Usage tracking
        self._requests_count = 0
        self._tokens_consumed = 0
        self._total_cost = 0.0
        self._total_latency = 0.0
        
        logger.info("OpenAI provider initialized", base_url=self.base_url)
    
    @property
    def name(self) -> str:
        """Provider name."""
        return "openai"
    
    @property
    def supported_models(self) -> List[str]:
        """List of supported model names."""
        return list(self.MODEL_PRICING.keys())
    
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
                "Sending chat completion request",
                model=request.model,
                message_count=len(request.messages),
                stream=request.stream,
            )
            
            # Make API request
            response = await self._make_request("POST", "/chat/completions", payload)
            
            # Parse response
            completion_response = ChatCompletionResponse(**response)
            
            # Track usage
            latency = time.time() - start_time
            self._track_usage(completion_response, latency)
            
            logger.info(
                "Chat completion successful",
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
                "Chat completion failed",
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
                "Starting streaming chat completion",
                model=request.model,
                message_count=len(request.messages),
            )
            
            # Make streaming API request
            async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ProviderError(f"API request failed: {error_text.decode()}")
                
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
                            logger.warning("Failed to parse streaming chunk", data=data)
                            continue
                        except ValidationError as e:
                            logger.warning("Invalid chunk format", error=str(e))
                            continue
            
            # Track usage (estimate for streaming)
            latency = time.time() - start_time
            self._requests_count += 1
            self._total_latency += latency
            
            logger.info(
                "Streaming chat completion completed",
                latency_ms=round(latency * 1000, 2),
            )
            
        except Exception as e:
            latency = time.time() - start_time
            logger.error(
                "Streaming chat completion failed",
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=round(latency * 1000, 2),
            )
            raise self._handle_error(e)
    
    async def health_check(self) -> ProviderHealth:
        """Check provider health."""
        start_time = time.time()
        
        try:
            # Make a simple API call to check health
            response = await self._make_request("GET", "/models")
            latency = time.time() - start_time
            
            return ProviderHealth(
                healthy=True,
                latency_ms=round(latency * 1000, 2),
                metadata={
                    "models_available": len(response.get("data", [])),
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
            cost_usd=self._total_cost,
            avg_latency_ms=round(avg_latency * 1000, 2),
        )
    
    def estimate_cost(self, request: ChatCompletionRequest) -> float:
        """Estimate the cost of a request in USD."""
        if request.model not in self.MODEL_PRICING:
            return 0.0
        
        input_price, output_price = self.MODEL_PRICING[request.model]
        
        # Rough token estimation (4 characters per token)
        prompt_tokens = sum(len(msg.content) for msg in request.messages) // 4
        estimated_output_tokens = request.max_tokens or 100
        
        input_cost = (prompt_tokens / 1000) * input_price
        output_cost = (estimated_output_tokens / 1000) * output_price
        
        return input_cost + output_cost
    
    async def validate_model(self, model: str) -> bool:
        """Validate if a model is supported."""
        return model in self.supported_models
    
    def _prepare_request_payload(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """Prepare request payload for OpenAI API."""
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
        
        # Add optional parameters
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
        """Make an HTTP request to the OpenAI API."""
        for attempt in range(self.max_retries + 1):
            try:
                if method == "GET":
                    response = await self._client.get(endpoint)
                else:
                    response = await self._client.post(endpoint, json=payload)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    raise ProviderRateLimitError(
                        "Rate limit exceeded",
                        retry_after=retry_after
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_message = error_data.get("error", {}).get("message", f"HTTP {response.status_code}")
                    raise ProviderError(error_message, status_code=response.status_code)
                    
            except httpx.TimeoutException:
                if attempt == self.max_retries:
                    raise ProviderTimeoutError("Request timeout")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except (ProviderError, ProviderRateLimitError):
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise ProviderError(f"Unexpected error: {str(e)}")
                await asyncio.sleep(2 ** attempt)
    
    def _handle_error(self, error: Exception) -> ProviderError:
        """Convert exceptions to appropriate provider errors."""
        if isinstance(error, ProviderError):
            return error
        elif isinstance(error, httpx.TimeoutException):
            return ProviderTimeoutError("Request timeout")
        else:
            return ProviderError(f"Unexpected error: {str(error)}")
    
    def _track_usage(self, response: ChatCompletionResponse, latency: float) -> None:
        """Track usage statistics."""
        self._requests_count += 1
        self._tokens_consumed += response.usage.total_tokens
        self._total_latency += latency
        
        # Calculate cost
        if response.model in self.MODEL_PRICING:
            input_price, output_price = self.MODEL_PRICING[response.model]
            cost = (
                (response.usage.prompt_tokens / 1000) * input_price +
                (response.usage.completion_tokens / 1000) * output_price
            )
            self._total_cost += cost
    
    async def close(self) -> None:
        """Close the provider and cleanup resources."""
        await self._client.aclose()
        logger.info("OpenAI provider closed")