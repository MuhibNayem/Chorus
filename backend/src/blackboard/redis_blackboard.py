import os
import json
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import redis.asyncio as redis
from .event_log import append_project_event

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class RedisBlackboard:
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._subscriptions: Dict[str, List[Callable]] = {}

    async def connect(self):
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()

    async def disconnect(self):
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def publish(self, channel: str, message: Dict[str, Any]):
        if not self._redis:
            await self.connect()
        msg_json = json.dumps(message, default=str)
        await self._redis.publish(channel, msg_json)

    async def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        if not self._redis:
            await self.connect()
        if channel not in self._subscriptions:
            self._subscriptions[channel] = []
            if not self._pubsub:
                self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(channel)
        self._subscriptions[channel].append(callback)

    async def listen(self):
        if not self._pubsub:
            return
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"]
                data = json.loads(message["data"])
                if channel in self._subscriptions:
                    for callback in self._subscriptions[channel]:
                        await callback(data)

    async def set(self, key: str, value: Any, ex: Optional[int] = None):
        if not self._redis:
            await self.connect()
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        await self._redis.set(key, value, ex=ex)

    async def get(self, key: str) -> Optional[Any]:
        if not self._redis:
            await self.connect()
        value = await self._redis.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def delete(self, key: str):
        if not self._redis:
            await self.connect()
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        if not self._redis:
            await self.connect()
        return await self._redis.exists(key) > 0

    async def sadd(self, key: str, *values):
        if not self._redis:
            await self.connect()
        await self._redis.sadd(key, *values)

    async def smembers(self, key: str) -> set:
        if not self._redis:
            await self.connect()
        return await self._redis.smembers(key)

    async def publish_agent_event(
        self,
        project_id: str,
        agent_name: str,
        event_type: str,
        content: str,
        data: Optional[Dict[str, Any]] = None,
    ):
        if not self._redis:
            await self.connect()
        channel = f"project:{project_id}:events"
        message = {
            "agent_name": agent_name,
            "agent_id": f"agent-{agent_name.lower()}",
            "type": event_type,
            "content": content,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        message = await append_project_event(self._redis, project_id, message)
        logging.getLogger("blackboard").info(
            f"[RedisBlackboard] publish project={project_id} agent={agent_name} type={event_type}"
        )
        await self.publish(channel, message)

    async def subscribe_agent_events(
        self, project_id: str, callback: Callable[[Dict[str, Any]], None]
    ):
        channel = f"project:{project_id}:events"
        await self.subscribe(channel, callback)

    async def set_task_status(
        self, project_id: str, task_id: str, status: str, result: Optional[Dict] = None
    ):
        key = f"project:{project_id}:task:{task_id}"
        value = {
            "status": status,
            "result": result,
            "updated_at": datetime.now().isoformat(),
        }
        await self.set(key, value, ex=86400)

    async def get_task_status(self, project_id: str, task_id: str) -> Optional[Dict]:
        key = f"project:{project_id}:task:{task_id}"
        return await self.get(key)

    async def set_project_state(self, project_id: str, state: Dict[str, Any]):
        key = f"project:{project_id}:state"
        await self.set(key, state, ex=86400)

    async def get_project_state(self, project_id: str) -> Optional[Dict]:
        key = f"project:{project_id}:state"
        return await self.get(key)

    async def acquire_lock(self, lock_name: str, timeout: int = 30) -> bool:
        lock_key = f"lock:{lock_name}"
        acquired = await self._redis.set(lock_key, "1", nx=True, ex=timeout)
        return bool(acquired)

    async def release_lock(self, lock_name: str):
        lock_key = f"lock:{lock_name}"
        await self.delete(lock_key)

    async def delete_project_keys(self, project_id: str) -> int:
        """Delete all Redis keys associated with a project. Returns count of deleted keys."""
        if not self._redis:
            await self.connect()
        pattern = f"project:{project_id}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self._redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        # Also delete the bare project state key if it exists without colon suffix
        state_key = f"project:{project_id}:state"
        if await self._redis.exists(state_key):
            await self._redis.delete(state_key)
            deleted += 1
        return deleted
