"""
Redis-based request queue management for StreamStack.

This module provides bounded queue functionality with overflow handling,
request prioritization, and comprehensive monitoring.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from pydantic import BaseModel

from streamstack.core.config import get_settings
from streamstack.core.logging import get_logger, get_request_id, get_user_id
from streamstack.observability.metrics import update_queue_depth


logger = get_logger("queue.manager")


class QueueItem(BaseModel):
    """Queue item model."""
    id: str
    request_data: Dict[str, Any]
    priority: int = 0
    created_at: float
    user_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    timeout: int = 300


class QueueStats(BaseModel):
    """Queue statistics model."""
    total_items: int
    pending_items: int
    processing_items: int
    completed_items: int
    failed_items: int
    avg_wait_time: float
    avg_processing_time: float


@dataclass
class QueueConfig:
    """Queue configuration."""
    max_size: int = 1000
    default_timeout: int = 300
    check_interval: float = 0.1
    priority_levels: int = 3
    cleanup_interval: int = 60


class RedisQueue:
    """Redis-based bounded queue with overflow handling."""
    
    def __init__(self, name: str, redis_client: redis.Redis, config: QueueConfig):
        self.name = name
        self.redis = redis_client
        self.config = config
        
        # Redis keys
        self.pending_key = f"queue:{name}:pending"
        self.processing_key = f"queue:{name}:processing"
        self.results_key = f"queue:{name}:results"
        self.stats_key = f"queue:{name}:stats"
        self.idempotency_key = f"queue:{name}:idempotency"
        
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("Redis queue initialized", name=name, config=config)
    
    async def start(self) -> None:
        """Start the queue manager."""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Queue manager started", name=self.name)
    
    async def stop(self) -> None:
        """Stop the queue manager."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Queue manager stopped", name=self.name)
    
    async def enqueue(
        self,
        request_data: Dict[str, Any],
        priority: int = 0,
        timeout: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> str:
        """
        Add an item to the queue.
        
        Args:
            request_data: Request data to queue
            priority: Priority level (higher = more priority)
            timeout: Request timeout in seconds
            idempotency_key: Optional idempotency key
            
        Returns:
            Queue item ID
            
        Raises:
            QueueFullError: If queue is at capacity
            DuplicateRequestError: If idempotency key already exists
        """
        # Check idempotency
        if idempotency_key:
            existing_id = await self.redis.get(f"{self.idempotency_key}:{idempotency_key}")
            if existing_id:
                logger.info("Duplicate request detected", idempotency_key=idempotency_key)
                return existing_id.decode()
        
        # Check queue capacity
        current_size = await self.redis.llen(self.pending_key)
        if current_size >= self.config.max_size:
            # Try to remove expired items first
            await self._cleanup_expired()
            current_size = await self.redis.llen(self.pending_key)
            
            if current_size >= self.config.max_size:
                logger.warning("Queue is full", name=self.name, size=current_size)
                raise QueueFullError(f"Queue {self.name} is full")
        
        # Create queue item
        item_id = str(uuid.uuid4())
        item = QueueItem(
            id=item_id,
            request_data=request_data,
            priority=priority,
            created_at=time.time(),
            user_id=get_user_id(),
            idempotency_key=idempotency_key,
            timeout=timeout or self.config.default_timeout
        )
        
        # Store item in Redis
        item_data = item.model_dump_json()
        
        async with self.redis.pipeline() as pipe:
            # Add to priority-based queue
            if priority > 0:
                await pipe.lpush(self.pending_key, item_data)
            else:
                await pipe.rpush(self.pending_key, item_data)
            
            # Store idempotency mapping
            if idempotency_key:
                await pipe.setex(
                    f"{self.idempotency_key}:{idempotency_key}",
                    item.timeout,
                    item_id
                )
            
            # Update stats
            await pipe.hincrby(self.stats_key, "total_items", 1)
            await pipe.execute()
        
        # Update metrics
        await self._update_queue_metrics()
        
        logger.info(
            "Item enqueued",
            item_id=item_id,
            priority=priority,
            queue_size=current_size + 1,
        )
        
        return item_id
    
    async def dequeue(self, timeout: float = 10.0) -> Optional[QueueItem]:
        """
        Remove and return an item from the queue.
        
        Args:
            timeout: Maximum time to wait for an item
            
        Returns:
            Queue item or None if timeout
        """
        try:
            # Blocking pop from pending queue
            result = await self.redis.blpop(self.pending_key, timeout=timeout)
            if not result:
                return None
            
            _, item_data = result
            item = QueueItem.model_validate_json(item_data)
            
            # Move to processing queue
            await self.redis.hset(
                self.processing_key,
                item.id,
                json.dumps({
                    "item": item.model_dump(),
                    "started_at": time.time(),
                    "worker_id": get_request_id() or "unknown"
                })
            )
            
            # Update metrics
            await self._update_queue_metrics()
            
            logger.info("Item dequeued", item_id=item.id)
            return item
            
        except Exception as e:
            logger.error("Failed to dequeue item", error=str(e))
            return None
    
    async def complete(self, item_id: str, result: Any = None, error: Optional[str] = None) -> None:
        """
        Mark an item as completed.
        
        Args:
            item_id: Item ID
            result: Optional result data
            error: Optional error message
        """
        processing_data = await self.redis.hget(self.processing_key, item_id)
        if not processing_data:
            logger.warning("Item not found in processing queue", item_id=item_id)
            return
        
        processing_info = json.loads(processing_data)
        started_at = processing_info["started_at"]
        processing_time = time.time() - started_at
        
        # Store result
        result_data = {
            "item_id": item_id,
            "completed_at": time.time(),
            "processing_time": processing_time,
            "result": result,
            "error": error,
            "success": error is None
        }
        
        async with self.redis.pipeline() as pipe:
            # Remove from processing
            await pipe.hdel(self.processing_key, item_id)
            
            # Store result (with expiration)
            await pipe.setex(
                f"{self.results_key}:{item_id}",
                600,  # 10 minutes
                json.dumps(result_data)
            )
            
            # Update stats
            if error:
                await pipe.hincrby(self.stats_key, "failed_items", 1)
            else:
                await pipe.hincrby(self.stats_key, "completed_items", 1)
            
            await pipe.execute()
        
        # Update metrics
        await self._update_queue_metrics()
        
        logger.info(
            "Item completed",
            item_id=item_id,
            processing_time_ms=round(processing_time * 1000, 2),
            success=error is None,
        )
    
    async def get_result(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the result of a completed item.
        
        Args:
            item_id: Item ID
            
        Returns:
            Result data or None if not found
        """
        result_data = await self.redis.get(f"{self.results_key}:{item_id}")
        if result_data:
            return json.loads(result_data)
        return None
    
    async def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        stats_data = await self.redis.hgetall(self.stats_key)
        
        pending_items = await self.redis.llen(self.pending_key)
        processing_items = await self.redis.hlen(self.processing_key)
        
        total_items = int(stats_data.get(b"total_items", 0))
        completed_items = int(stats_data.get(b"completed_items", 0))
        failed_items = int(stats_data.get(b"failed_items", 0))
        
        return QueueStats(
            total_items=total_items,
            pending_items=pending_items,
            processing_items=processing_items,
            completed_items=completed_items,
            failed_items=failed_items,
            avg_wait_time=0.0,  # TODO: Calculate from metrics
            avg_processing_time=0.0,  # TODO: Calculate from metrics
        )
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup task."""
        while self._running:
            try:
                await self._cleanup_expired()
                await asyncio.sleep(self.config.cleanup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup loop error", error=str(e))
                await asyncio.sleep(5)
    
    async def _cleanup_expired(self) -> None:
        """Clean up expired items."""
        current_time = time.time()
        removed_count = 0
        
        # Clean up expired processing items
        processing_items = await self.redis.hgetall(self.processing_key)
        for item_id, data in processing_items.items():
            try:
                processing_info = json.loads(data)
                item_data = processing_info["item"]
                
                # Check if item has expired
                if current_time - item_data["created_at"] > item_data["timeout"]:
                    await self.redis.hdel(self.processing_key, item_id)
                    removed_count += 1
                    
                    logger.warning("Expired processing item removed", item_id=item_id)
                    
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Invalid processing item data", item_id=item_id, error=str(e))
                await self.redis.hdel(self.processing_key, item_id)
        
        if removed_count > 0:
            logger.info("Cleanup completed", removed_items=removed_count)
    
    async def _update_queue_metrics(self) -> None:
        """Update Prometheus metrics."""
        try:
            stats = await self.get_stats()
            update_queue_depth(self.name, stats.pending_items)
        except Exception as e:
            logger.warning("Failed to update queue metrics", error=str(e))


class QueueManager:
    """Manager for multiple Redis queues."""
    
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._queues: Dict[str, RedisQueue] = {}
        self._config: Optional[QueueConfig] = None
    
    async def initialize(self, settings) -> None:
        """Initialize the queue manager."""
        self._config = QueueConfig(
            max_size=settings.max_queue_size,
            default_timeout=settings.request_timeout,
            check_interval=settings.queue_check_interval,
        )
        
        # Create Redis connection
        self._redis = redis.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=False,
        )
        
        # Test connection
        await self._redis.ping()
        
        # Create default queue
        await self.create_queue("default")
        
        logger.info("Queue manager initialized", config=self._config)
    
    async def create_queue(self, name: str) -> RedisQueue:
        """Create a new queue."""
        if name in self._queues:
            return self._queues[name]
        
        queue = RedisQueue(name, self._redis, self._config)
        await queue.start()
        self._queues[name] = queue
        
        logger.info("Queue created", name=name)
        return queue
    
    def get_queue(self, name: str = "default") -> RedisQueue:
        """Get a queue by name."""
        if name not in self._queues:
            raise ValueError(f"Queue '{name}' not found")
        return self._queues[name]
    
    async def close(self) -> None:
        """Close the queue manager."""
        for queue in self._queues.values():
            await queue.stop()
        
        if self._redis:
            await self._redis.close()
        
        logger.info("Queue manager closed")


class QueueFullError(Exception):
    """Exception raised when queue is full."""
    pass


class DuplicateRequestError(Exception):
    """Exception raised for duplicate idempotency key."""
    pass


# Global queue manager instance
queue_manager = QueueManager()


def get_queue_manager() -> QueueManager:
    """Get the global queue manager instance."""
    return queue_manager