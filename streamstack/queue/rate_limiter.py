"""
Token bucket rate limiting implementation using Redis.

This module provides distributed rate limiting with token bucket algorithm,
supporting both request-based and token-based limits with Redis backend.
"""

import asyncio
import time
from typing import Dict, NamedTuple, Optional

import redis.asyncio as redis

from streamstack.core.config import get_settings
from streamstack.core.logging import get_logger


logger = get_logger("queue.rate_limiter")


class RateLimitResult(NamedTuple):
    """Rate limit check result."""
    allowed: bool
    remaining: int
    reset_time: int
    retry_after: Optional[int] = None


class TokenBucket:
    """Token bucket rate limiter using Redis."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        key: str,
        capacity: int,
        refill_rate: float,
        refill_period: int = 60
    ):
        """
        Initialize token bucket.
        
        Args:
            redis_client: Redis client
            key: Redis key for this bucket
            capacity: Maximum tokens in bucket
            refill_rate: Tokens to add per refill period
            refill_period: Refill period in seconds
        """
        self.redis = redis_client
        self.key = key
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_period = refill_period
        
        # Lua script for atomic token bucket operation
        self.lua_script = self.redis.register_script("""
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local refill_rate = tonumber(ARGV[2])
            local refill_period = tonumber(ARGV[3])
            local requested = tonumber(ARGV[4])
            local now = tonumber(ARGV[5])
            
            local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
            local tokens = tonumber(bucket[1])
            local last_refill = tonumber(bucket[2])
            
            -- Initialize bucket if it doesn't exist
            if tokens == nil then
                tokens = capacity
                last_refill = now
            end
            
            -- Calculate tokens to add based on time elapsed
            local time_elapsed = now - last_refill
            local periods_elapsed = math.floor(time_elapsed / refill_period)
            
            if periods_elapsed > 0 then
                tokens = math.min(capacity, tokens + (periods_elapsed * refill_rate))
                last_refill = last_refill + (periods_elapsed * refill_period)
            end
            
            -- Check if request can be fulfilled
            local allowed = 0
            local retry_after = 0
            
            if tokens >= requested then
                tokens = tokens - requested
                allowed = 1
            else
                -- Calculate when enough tokens will be available
                local tokens_needed = requested - tokens
                local periods_needed = math.ceil(tokens_needed / refill_rate)
                retry_after = periods_needed * refill_period
            end
            
            -- Update bucket state
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('EXPIRE', key, refill_period * 2)  -- Auto-expire old buckets
            
            -- Calculate reset time
            local reset_time = last_refill + refill_period
            
            return {allowed, tokens, reset_time, retry_after}
        """)
    
    async def consume(self, tokens: int = 1) -> RateLimitResult:
        """
        Attempt to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            Rate limit result
        """
        now = int(time.time())
        
        try:
            result = await self.lua_script(
                keys=[self.key],
                args=[self.capacity, self.refill_rate, self.refill_period, tokens, now]
            )
            
            allowed, remaining, reset_time, retry_after = result
            
            return RateLimitResult(
                allowed=bool(allowed),
                remaining=int(remaining),
                reset_time=int(reset_time),
                retry_after=int(retry_after) if retry_after > 0 else None
            )
            
        except Exception as e:
            logger.error("Rate limit check failed", error=str(e))
            # Fail open - allow request if Redis is unavailable
            return RateLimitResult(
                allowed=True,
                remaining=self.capacity,
                reset_time=now + self.refill_period
            )


class RateLimiter:
    """Multi-dimensional rate limiter with token bucket algorithm."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._buckets: Dict[str, TokenBucket] = {}
        
        settings = get_settings()
        
        # Default rate limits
        self.request_limit = settings.rate_limit_requests_per_minute
        self.token_limit = settings.rate_limit_tokens_per_minute
        self.burst_size = settings.rate_limit_burst_size
        
        logger.info(
            "Rate limiter initialized",
            request_limit=self.request_limit,
            token_limit=self.token_limit,
            burst_size=self.burst_size,
        )
    
    def _get_bucket(
        self,
        identifier: str,
        limit_type: str,
        capacity: int,
        refill_rate: float,
        refill_period: int = 60
    ) -> TokenBucket:
        """Get or create a token bucket."""
        key = f"rate_limit:{limit_type}:{identifier}"
        
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                self.redis,
                key,
                capacity,
                refill_rate,
                refill_period
            )
        
        return self._buckets[key]
    
    async def check_request_limit(self, identifier: str) -> RateLimitResult:
        """
        Check request rate limit.
        
        Args:
            identifier: User/IP identifier
            
        Returns:
            Rate limit result
        """
        bucket = self._get_bucket(
            identifier,
            "requests",
            self.request_limit + self.burst_size,
            self.request_limit,
            60
        )
        
        result = await bucket.consume(1)
        
        logger.debug(
            "Request rate limit check",
            identifier=identifier,
            allowed=result.allowed,
            remaining=result.remaining,
        )
        
        return result
    
    async def check_token_limit(self, identifier: str, tokens: int) -> RateLimitResult:
        """
        Check token rate limit.
        
        Args:
            identifier: User/IP identifier
            tokens: Number of tokens to consume
            
        Returns:
            Rate limit result
        """
        bucket = self._get_bucket(
            identifier,
            "tokens",
            self.token_limit + (self.burst_size * 100),  # Larger burst for tokens
            self.token_limit,
            60
        )
        
        result = await bucket.consume(tokens)
        
        logger.debug(
            "Token rate limit check",
            identifier=identifier,
            tokens=tokens,
            allowed=result.allowed,
            remaining=result.remaining,
        )
        
        return result
    
    async def check_limits(
        self,
        identifier: str,
        estimated_tokens: int = 100
    ) -> RateLimitResult:
        """
        Check both request and token limits.
        
        Args:
            identifier: User/IP identifier
            estimated_tokens: Estimated tokens for the request
            
        Returns:
            Combined rate limit result
        """
        # Check request limit first (cheaper)
        request_result = await self.check_request_limit(identifier)
        if not request_result.allowed:
            return request_result
        
        # Check token limit
        token_result = await self.check_token_limit(identifier, estimated_tokens)
        if not token_result.allowed:
            return token_result
        
        # Both limits passed
        return RateLimitResult(
            allowed=True,
            remaining=min(request_result.remaining, token_result.remaining // estimated_tokens),
            reset_time=max(request_result.reset_time, token_result.reset_time)
        )
    
    async def get_limits_info(self, identifier: str) -> Dict[str, RateLimitResult]:
        """
        Get current limits information without consuming tokens.
        
        Args:
            identifier: User/IP identifier
            
        Returns:
            Dictionary with request and token limit info
        """
        # Get current state without consuming
        request_bucket = self._get_bucket(
            identifier,
            "requests",
            self.request_limit + self.burst_size,
            self.request_limit,
            60
        )
        
        token_bucket = self._get_bucket(
            identifier,
            "tokens",
            self.token_limit + (self.burst_size * 100),
            self.token_limit,
            60
        )
        
        # Check without consuming (0 tokens)
        request_info = await request_bucket.consume(0)
        token_info = await token_bucket.consume(0)
        
        return {
            "requests": request_info,
            "tokens": token_info
        }


class RateLimitManager:
    """Manager for rate limiting functionality."""
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._rate_limiter: Optional[RateLimiter] = None
    
    async def initialize(self, settings) -> None:
        """Initialize the rate limit manager."""
        # Create Redis connection
        self._redis = redis.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=False,
        )
        
        # Test connection
        await self._redis.ping()
        
        # Create rate limiter
        self._rate_limiter = RateLimiter(self._redis)
        
        logger.info("Rate limit manager initialized")
    
    def get_rate_limiter(self) -> RateLimiter:
        """Get the rate limiter instance."""
        if self._rate_limiter is None:
            raise RuntimeError("Rate limiter not initialized")
        return self._rate_limiter
    
    async def close(self) -> None:
        """Close the rate limit manager."""
        if self._redis:
            await self._redis.close()
        logger.info("Rate limit manager closed")


# Global rate limit manager instance
rate_limit_manager = RateLimitManager()


def get_rate_limit_manager() -> RateLimitManager:
    """Get the global rate limit manager instance."""
    return rate_limit_manager