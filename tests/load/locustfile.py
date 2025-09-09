"""
Locust load testing script for StreamStack LLM API.

This script provides comprehensive load testing scenarios for the StreamStack API,
including chat completions, streaming, and various load patterns.
"""

import json
import random
import time
from typing import Dict, List

from locust import HttpUser, task, between
from locust.exception import RescheduleTask


class StreamStackUser(HttpUser):
    """Simulated user for StreamStack API load testing."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Called when a user starts."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": "test-api-key",
        })
    
    @task(3)
    def chat_completion_simple(self):
        """Test simple chat completion."""
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ],
            "temperature": 0.7,
            "max_tokens": 100,
            "stream": False
        }
        
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    response.success()
                else:
                    response.failure("Invalid response format")
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(2)
    def chat_completion_conversation(self):
        """Test chat completion with conversation history."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is machine learning?"},
            {"role": "assistant", "content": "Machine learning is a subset of artificial intelligence..."},
            {"role": "user", "content": "Can you give me an example?"}
        ]
        
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 200,
            "stream": False
        }
        
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(1)
    def chat_completion_streaming(self):
        """Test streaming chat completion."""
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": "Tell me a short story about a robot."}
            ],
            "temperature": 0.9,
            "max_tokens": 300,
            "stream": True
        }
        
        start_time = time.time()
        chunks_received = 0
        
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            stream=True,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    for line in response.iter_lines(decode_unicode=True):
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            if data == "[DONE]":
                                break
                            try:
                                json.loads(data)
                                chunks_received += 1
                            except json.JSONDecodeError:
                                continue
                    
                    duration = time.time() - start_time
                    if chunks_received > 0:
                        response.success()
                        # Log streaming metrics
                        self.environment.events.request.fire(
                            request_type="STREAM",
                            name="/v1/chat/completions (streaming)",
                            response_time=duration * 1000,
                            response_length=chunks_received,
                            exception=None,
                            context={}
                        )
                    else:
                        response.failure("No chunks received")
                        
                except Exception as e:
                    response.failure(f"Streaming error: {str(e)}")
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(1)
    def chat_completion_with_idempotency(self):
        """Test chat completion with idempotency key."""
        idempotency_key = f"test-{random.randint(1000, 9999)}-{int(time.time())}"
        
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": "What is the weather like?"}
            ],
            "temperature": 0.5,
            "max_tokens": 50,
            "stream": False
        }
        
        headers = {"Idempotency-Key": idempotency_key}
        
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers=headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(4)
    def health_check(self):
        """Test health check endpoint."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") in ["healthy", "degraded"]:
                    response.success()
                else:
                    response.failure("Unhealthy status")
            else:
                response.failure(f"HTTP {response.status_code}")
    
    @task(1)
    def metrics_check(self):
        """Test metrics endpoint."""
        with self.client.get("/metrics", catch_response=True) as response:
            if response.status_code == 200:
                if "streamstack_" in response.text:
                    response.success()
                else:
                    response.failure("No StreamStack metrics found")
            else:
                response.failure(f"HTTP {response.status_code}")


class StreamStackHeavyUser(HttpUser):
    """Heavy user for stress testing."""
    
    wait_time = between(0.1, 0.5)  # Aggressive load
    weight = 1  # Lower weight than normal users
    
    def on_start(self):
        """Called when a user starts."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": "stress-test-key",
        })
    
    @task(5)
    def rapid_fire_requests(self):
        """Send rapid-fire requests to test rate limiting."""
        payloads = [
            {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": f"Quick question {i}"}],
                "max_tokens": 10,
                "stream": False
            }
            for i in range(5)
        ]
        
        for payload in payloads:
            with self.client.post(
                "/v1/chat/completions",
                json=payload,
                catch_response=True
            ) as response:
                if response.status_code == 429:
                    # Rate limiting is working
                    response.success()
                    break
                elif response.status_code == 200:
                    response.success()
                else:
                    response.failure(f"HTTP {response.status_code}")
            
            time.sleep(0.05)  # Brief pause between requests


class StreamStackBurstUser(HttpUser):
    """Burst user for testing sudden load spikes."""
    
    wait_time = between(10, 30)  # Long pauses between bursts
    weight = 1
    
    def on_start(self):
        """Called when a user starts."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "X-API-Key": "burst-test-key",
        })
    
    @task(1)
    def burst_requests(self):
        """Send a burst of requests."""
        burst_size = random.randint(5, 15)
        
        for i in range(burst_size):
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "user", "content": f"Burst request {i + 1} of {burst_size}"}
                ],
                "temperature": random.uniform(0.1, 1.0),
                "max_tokens": random.randint(50, 150),
                "stream": random.choice([True, False])
            }
            
            with self.client.post(
                "/v1/chat/completions",
                json=payload,
                catch_response=True
            ) as response:
                if response.status_code in [200, 429]:
                    response.success()
                else:
                    response.failure(f"HTTP {response.status_code}")


def create_custom_stats():
    """Create custom statistics for the load test."""
    pass


# Configure user classes and their weights
if __name__ == "__main__":
    # This file can also be run directly with locust
    # Example: locust -f locustfile.py --host=http://localhost:8000
    pass