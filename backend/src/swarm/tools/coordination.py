import os
import json
import time
import logging
import redis.asyncio as redis
from typing import Dict, Any
from langchain_core.tools import tool
from .workspace_tools import get_project_id

logger = logging.getLogger("tools")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _dependency_result(dependency: str, data: Any) -> Dict[str, Any]:
    if isinstance(data, dict) and data.get("status") in {"error", "failed"}:
        return {"status": "error", "dependency": dependency, "data": data}
    return {"status": "success", "dependency": dependency, "data": data}


@tool("wait_on_agent")
async def wait_on_agent(dependency: str) -> Dict[str, Any]:
    """[COMPATIBILITY-ONLY] Wait for another agent to complete a specific task.

    Deprecated: Agents should use `wait_for_claim` instead. This tool is kept
    only for backward compatibility during the claim protocol transition.

    Uses Redis pub/sub with persistent storage for 100% reliable delivery.
    Blocks indefinitely until dependency is satisfied (supports hours-long waits).

    Args:
        dependency: The name of the dependency to wait for (e.g., 'backend_api')
    """
    logger.warning(
        "[DEPRECATED] wait_on_agent called for '%s'. "
        "Agents should use wait_for_claim instead.",
        dependency,
    )
    project_id = get_project_id()
    dep_key = f"project:{project_id}:dep:{dependency}"
    channel = f"project:{project_id}:events"

    r = redis.from_url(REDIS_URL, decode_responses=True)

    try:
        # 1. Immediate path: Check if dependency is already satisfied
        data = await r.get(dep_key)
        if data:
            logger.info(f"[wait_on_agent] Dependency '{dependency}' ready immediately.")
            try:
                data = json.loads(data)
            except:
                pass
            await r.delete(dep_key)
            logger.info(f"[wait_on_agent] Consumed dependency key: {dep_key}")
            return _dependency_result(dependency, data)

        # 2. Infinite wait via pub/sub with persistent backup
        logger.info(f"[wait_on_agent] Entering infinite wait for: {dependency}")

        pubsub = r.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(channel)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = await r.get(dep_key)
                        if data:
                            logger.info(f"[wait_on_agent] Dependency '{dependency}' satisfied via event.")
                            try:
                                data = json.loads(data)
                            except:
                                pass
                            await r.delete(dep_key)
                            logger.info(f"[wait_on_agent] Consumed dependency key: {dep_key}")
                            return _dependency_result(dependency, data)
                    except Exception as e:
                        logger.debug(f"[wait_on_agent] Error checking dependency: {e}")
                        continue
        except redis.ConnectionError:
            logger.warning(f"[wait_on_agent] Connection lost, checking dependency one last time.")
            data = await r.get(dep_key)
            if data:
                try:
                    data = json.loads(data)
                except:
                    pass
                await r.delete(dep_key)
                return _dependency_result(dependency, data)
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
    finally:
        await r.aclose()

    return {"status": "error", "error": "Unexpected exit from wait loop"}


async def signal_dependency_ready(dependency: str, data: str) -> Dict[str, Any]:
    project_id = get_project_id()
    dep_key = f"project:{project_id}:dep:{dependency}"

    r = redis.from_url(REDIS_URL, decode_responses=True)

    try:
        logger.info(f"[signal_ready] Signaling: {dependency}")

        # 1. Store the dependency value persistently (survives disconnects, restarts)
        await r.set(dep_key, data)

        # 2. Publish event to wake up all subscribed agents
        message = {
            "type": "dependency_ready",
            "agent_name": "system",
            "content": f"Dependency {dependency} is now ready.",
            "data": {"dependency": dependency},
            "timestamp": int(time.time() * 1000)
        }
        await r.publish(f"project:{project_id}:events", json.dumps(message))

        logger.info(f"[signal_ready] Published event for: {dependency}")

        return {
            "status": "success",
            "dependency": dependency,
            "message": f"Successfully signaled {dependency} is ready.",
        }
    finally:
        await r.aclose()


@tool("signal_ready")
async def signal_ready(dependency: str, data: str) -> Dict[str, Any]:
    """[COMPATIBILITY-ONLY] Signal that a task is complete.

    Deprecated: Agents should use `publish_claim` instead. This tool is kept
    only for backward compatibility during the claim protocol transition.

    Publishes event to wake up all waiting agents. Data persists in Redis
    until explicitly consumed by wait_on_agent.

    Args:
        dependency: The name of the dependency you are fulfilling (e.g., 'backend_api')
        data: The JSON string or description of the data being shared
    """
    logger.warning(
        "[DEPRECATED] signal_ready called for '%s'. "
        "Agents should use publish_claim instead.",
        dependency,
    )
    return await signal_dependency_ready(dependency, data)
