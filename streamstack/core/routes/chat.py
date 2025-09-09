"""
OpenAI-compatible chat completions API endpoint with SSE support.
"""

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from streamstack.core.config import get_settings
from streamstack.core.logging import get_logger, get_request_id
from streamstack.providers.base import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from streamstack.providers.manager import get_provider_manager

router = APIRouter(tags=["chat"])
logger = get_logger("routes.chat")


async def get_rate_limit_info(request: Request) -> Dict[str, Any]:
    """Check rate limiting for the request."""
    try:
        from streamstack.queue.rate_limiter import get_rate_limit_manager
        
        # Get client identifier (IP address or user ID)
        client_ip = request.client.host if request.client else "unknown"
        user_id = request.headers.get("X-User-ID") or client_ip
        
        # Estimate tokens for the request (basic estimation)
        estimated_tokens = 100  # Default estimate
        
        rate_limiter = get_rate_limit_manager().get_rate_limiter()
        result = await rate_limiter.check_limits(user_id, estimated_tokens)
        
        return {
            "allowed": result.allowed,
            "requests_remaining": result.remaining,
            "tokens_remaining": result.remaining * estimated_tokens,
            "reset_time": result.reset_time,
            "retry_after": result.retry_after,
        }
        
    except Exception as e:
        logger.warning("Rate limit check failed, allowing request", error=str(e))
        # Fail open - allow request if rate limiting is unavailable
        return {
            "allowed": True,
            "requests_remaining": 95,
            "tokens_remaining": 9500,
            "reset_time": int(time.time()) + 60,
        }


async def check_idempotency(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
) -> Optional[str]:
    """Check for idempotency key and handle duplicate requests."""
    if idempotency_key:
        # TODO: Implement idempotency logic with Redis
        logger.info("Idempotency key provided", key=idempotency_key)
    return idempotency_key


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_request: Request,
    rate_limit_info: Dict[str, Any] = Depends(get_rate_limit_info),
    idempotency_key: Optional[str] = Depends(check_idempotency),
) -> Union[ChatCompletionResponse, StreamingResponse]:
    """
    Create a chat completion, optionally streaming the response.
    
    This endpoint is compatible with the OpenAI chat completions API.
    """
    settings = get_settings()
    request_id = get_request_id() or "unknown"
    
    # Check rate limits
    if not rate_limit_info["allowed"]:
        retry_after = rate_limit_info.get("retry_after", 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit-Requests": str(rate_limit_info.get("requests_remaining", 0)),
                "X-RateLimit-Remaining-Requests": str(rate_limit_info.get("requests_remaining", 0)),
                "X-RateLimit-Reset-Requests": str(rate_limit_info.get("reset_time", 0)),
            }
        )
    
    logger.info(
        "Chat completion request received",
        model=request.model,
        message_count=len(request.messages),
        stream=request.stream,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )
    
    try:
        # Get provider
        provider_manager = get_provider_manager()
        provider = provider_manager.get_provider()
        
        # Validate model
        if not await provider.validate_model(request.model):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{request.model}' is not supported by provider '{provider.name}'"
            )
        
        if request.stream:
            # Return streaming response
            return StreamingResponse(
                stream_chat_completion(provider, request, request_id),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": request_id,
                }
            )
        else:
            # Return complete response
            return await provider.chat_completion(request)
            
    except ProviderRateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Provider rate limit exceeded",
            headers={"Retry-After": str(e.retry_after or 60)}
        )
    except ProviderUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM provider unavailable",
            headers={"Retry-After": str(e.retry_after or 60)}
        )
    except ProviderError as e:
        raise HTTPException(
            status_code=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=e.message
        )
    except Exception as e:
        logger.error("Chat completion failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat completion"
        )


async def stream_chat_completion(
    provider,
    request: ChatCompletionRequest,
    request_id: str
) -> AsyncGenerator[str, None]:
    """Stream chat completion chunks using Server-Sent Events."""
    try:
        async for chunk in provider.chat_completion_stream(request):
            yield f"data: {chunk.model_dump_json()}\n\n"
        
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error("Streaming error", error=str(e))
        error_chunk = {
            "error": {
                "message": "An error occurred during streaming",
                "type": "server_error",
                "code": "internal_error"
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"