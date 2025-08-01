import json
import aiohttp
import os
import logging
import asyncio
from shared.payloads import *
from shared.rate_limiter import RateLimiter
from redis.asyncio import Redis


class Worker:
    def __init__(self, input_queue: str, data_type: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.redis_url = os.environ.get("REDIS_URL")
        self.input_queue = input_queue
        self.data_type = data_type
        self.session = None
        self.redis = None

    async def init_redis(self) -> bool:
        try:
            self.redis = Redis.from_url(self.redis_url, decode_responses=True)
            await self.redis.ping()
            return True
        except Exception as e:
            self.logger.error(f"REDIS CONNECTION FAILED: {str(e)}")
            return False

    async def open_connection(self):
        """Initialize aiohttp session and Redis connection"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return await self.init_redis()

    async def close_connection(self):
        """Close connections"""
        if self.session:
            await self.session.close()
            self.session = None
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    async def __aenter__(self):
        await self.open_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_connection()

    async def process_task(self, task_data: dict) -> dict:
        """To be implemented by child classes (template method)"""
        raise NotImplementedError("Child classes must implement process_task()")

    async def run_worker(self):
        """
        Main worker loop for processing tasks from Redis.
        The result is in Redis under the same key as the task. Ex: "search:AAPL,2022-01-01"
        """
        await self.open_connection()
        self.logger.info(f"{self.__class__.__name__} STARTED. Listening on {self.input_queue}")

        try:
            while True:
                _, task_key = await self.redis.blpop([self.input_queue], timeout=0)
                if task_key:
                    try:
                        prefix, task = task_key.split(":", 1)
                        result = await self.process_task(task)
                        await self.redis.set(
                            task_key,
                            json.dumps(result),
                        )

                    except json.JSONDecodeError:
                        self.logger.error(f"Invalid JSON task: {task_key}")
                    except Exception as e:
                        self.logger.error(f"Task processing failed: {str(e)}")
        except asyncio.CancelledError:
            self.logger.info("Worker shutdown requested")
        finally:
            await self.close_connection()
            self.logger.info("Worker shutdown complete")
