"""
Abstract base classes for LLM providers.

This module defines the interfaces that all LLM providers must implement,
enabling pluggable provider support for different LLM backends.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """Chat completion request parameters."""
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = 1.0
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0
    stop: Optional[List[str]] = None
    stream: bool = False
    user: Optional[str] = None


class ChatCompletionChoice(BaseModel):
    """A single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
    """Token usage information."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """Complete chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage


class ChatCompletionChunk(BaseModel):
    """Streaming chat completion chunk."""
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[Dict[str, Any]]


class ProviderHealth(BaseModel):
    """Provider health status."""
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}


class ProviderUsage(BaseModel):
    """Provider usage statistics."""
    requests_count: int
    tokens_consumed: int
    cost_usd: float
    avg_latency_ms: float


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the provider with configuration."""
        self.config = config
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass
    
    @property
    @abstractmethod
    def supported_models(self) -> List[str]:
        """List of supported model names."""
        pass
    
    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """
        Create a chat completion.
        
        Args:
            request: Chat completion request parameters
            
        Returns:
            Complete chat completion response
            
        Raises:
            ProviderError: If the request fails
        """
        pass
    
    @abstractmethod
    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """
        Create a streaming chat completion.
        
        Args:
            request: Chat completion request parameters
            
        Yields:
            Chat completion chunks
            
        Raises:
            ProviderError: If the request fails
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """
        Check provider health.
        
        Returns:
            Provider health status
        """
        pass
    
    @abstractmethod
    async def get_usage_stats(self) -> ProviderUsage:
        """
        Get provider usage statistics.
        
        Returns:
            Usage statistics
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, request: ChatCompletionRequest) -> float:
        """
        Estimate the cost of a request in USD.
        
        Args:
            request: Chat completion request
            
        Returns:
            Estimated cost in USD
        """
        pass
    
    @abstractmethod
    async def validate_model(self, model: str) -> bool:
        """
        Validate if a model is supported.
        
        Args:
            model: Model name to validate
            
        Returns:
            True if model is supported
        """
        pass


class ProviderError(Exception):
    """Base exception for provider errors."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        retry_after: Optional[int] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.retry_after = retry_after


class ProviderTimeoutError(ProviderError):
    """Provider request timeout error."""
    pass


class ProviderRateLimitError(ProviderError):
    """Provider rate limit exceeded error."""
    pass


class ProviderAuthenticationError(ProviderError):
    """Provider authentication error."""
    pass


class ProviderNotFoundError(ProviderError):
    """Provider or model not found error."""
    pass


class ProviderUnavailableError(ProviderError):
    """Provider temporarily unavailable error."""
    pass