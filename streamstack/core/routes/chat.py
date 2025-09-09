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

router = APIRouter(tags=["chat"])
logger = get_logger("routes.chat")


class ChatMessage(BaseModel):
    """A single chat message."""
    role: str = Field(..., description="Message role: system, user, or assistant")
    content: str = Field(..., description="Message content")
    name: Optional[str] = Field(None, description="Optional name of the message author")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str = Field(..., description="Model to use for completion")
    messages: List[ChatMessage] = Field(..., description="List of messages in the conversation")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, ge=1, description="Maximum tokens to generate")
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0, description="Nucleus sampling parameter")
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0, description="Frequency penalty")
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0, description="Presence penalty")
    stop: Optional[Union[str, List[str]]] = Field(default=None, description="Stop sequences")
    stream: bool = Field(default=False, description="Whether to stream the response")
    user: Optional[str] = Field(default=None, description="User identifier")


class ChatCompletionChoice(BaseModel):
    """A single completion choice."""
    index: int = Field(..., description="Choice index")
    message: ChatMessage = Field(..., description="Generated message")
    finish_reason: Optional[str] = Field(None, description="Reason for completion finish")


class ChatCompletionUsage(BaseModel):
    """Token usage information."""
    prompt_tokens: int = Field(..., description="Tokens in the prompt")
    completion_tokens: int = Field(..., description="Tokens in the completion")
    total_tokens: int = Field(..., description="Total tokens used")


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str = Field(..., description="Completion ID")
    object: str = Field(default="chat.completion", description="Object type")
    created: int = Field(..., description="Creation timestamp")
    model: str = Field(..., description="Model used")
    choices: List[ChatCompletionChoice] = Field(..., description="Completion choices")
    usage: ChatCompletionUsage = Field(..., description="Token usage")


class ChatCompletionChunk(BaseModel):
    """Streaming chat completion chunk."""
    id: str = Field(..., description="Completion ID")
    object: str = Field(default="chat.completion.chunk", description="Object type")
    created: int = Field(..., description="Creation timestamp")
    model: str = Field(..., description="Model used")
    choices: List[Dict[str, Any]] = Field(..., description="Streaming choices")


async def get_rate_limit_info(request: Request) -> Dict[str, Any]:
    """Check rate limiting for the request."""
    # TODO: Implement actual rate limiting logic
    return {
        "allowed": True,
        "requests_remaining": 95,
        "tokens_remaining": 9500,
        "reset_time": int(time.time()) + 60
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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit-Requests": "100",
                "X-RateLimit-Remaining-Requests": str(rate_limit_info["requests_remaining"]),
                "X-RateLimit-Reset-Requests": str(rate_limit_info["reset_time"]),
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
        if request.stream:
            # Return streaming response
            return StreamingResponse(
                stream_chat_completion(request, request_id),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": request_id,
                }
            )
        else:
            # Return complete response
            return await create_complete_chat_completion(request, request_id)
            
    except Exception as e:
        logger.error("Chat completion failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat completion"
        )


async def stream_chat_completion(
    request: ChatCompletionRequest,
    request_id: str
) -> AsyncGenerator[str, None]:
    """Stream chat completion chunks using Server-Sent Events."""
    completion_id = f"chatcmpl-{request_id}"
    created = int(time.time())
    
    try:
        # TODO: Get actual LLM provider and stream response
        # For now, simulate streaming
        content_tokens = ["Hello", " there", "!", " How", " can", " I", " help", " you", " today", "?"]
        
        for i, token in enumerate(content_tokens):
            chunk = ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=request.model,
                choices=[{
                    "index": 0,
                    "delta": {"content": token} if i > 0 else {"role": "assistant", "content": token},
                    "finish_reason": None
                }]
            )
            
            yield f"data: {chunk.model_dump_json()}\n\n"
            
            # Simulate processing delay
            await asyncio.sleep(0.1)
        
        # Send final chunk
        final_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=request.model,
            choices=[{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        )
        
        yield f"data: {final_chunk.model_dump_json()}\n\n"
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


async def create_complete_chat_completion(
    request: ChatCompletionRequest,
    request_id: str
) -> ChatCompletionResponse:
    """Create a complete (non-streaming) chat completion."""
    completion_id = f"chatcmpl-{request_id}"
    created = int(time.time())
    
    # TODO: Get actual LLM provider and generate response
    # For now, return a mock response
    
    response_message = ChatMessage(
        role="assistant",
        content="Hello there! How can I help you today?"
    )
    
    choice = ChatCompletionChoice(
        index=0,
        message=response_message,
        finish_reason="stop"
    )
    
    usage = ChatCompletionUsage(
        prompt_tokens=len(" ".join(msg.content for msg in request.messages)) // 4,  # Rough estimate
        completion_tokens=len(response_message.content) // 4,  # Rough estimate
        total_tokens=0
    )
    usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
    
    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=request.model,
        choices=[choice],
        usage=usage
    )