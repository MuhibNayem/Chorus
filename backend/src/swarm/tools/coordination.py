import os
import json
import time
import logging
import redis
from typing import Dict, Any
from langchain_core.tools import tool
from .workspace_tools import get_project_id

logger = logging.getLogger("tools")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@tool("wait_on_agent")
def wait_on_agent(dependency: str, timeout: int = 120) -> Dict[str, Any]:
    """Wait for another agent to complete a specific task or publish a spec.
    This call BLOCKS your execution until the dependency is met.

    Args:
        dependency: The name of the dependency to wait for (e.g., 'backend_api')
        timeout: How long to wait in seconds (default 120)
    """
    project_id = get_project_id()
    dep_key = f"project:{project_id}:dep:{dependency}"

    # Use a fresh sync Redis connection — thread-safe, no event-loop binding issues
    r = redis.from_url(REDIS_URL, decode_responses=True)

    logger.info(f"[Tool:wait_on_agent] Agent waiting for: {dependency}")

    start_time = time.time()
    while time.time() - start_time < timeout:
        data = r.get(dep_key)
        if data:
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass
            logger.info(f"[Tool:wait_on_agent] Dependency met: {dependency}")
            return {
                "status": "success",
                "dependency": dependency,
                "data": data,
                "message": f"Dependency {dependency} is now ready.",
            }
        time.sleep(2)

    logger.warning(f"[Tool:wait_on_agent] Timeout waiting for {dependency}")
    return {
        "status": "timeout",
        "error": f"Timed out waiting for {dependency} after {timeout}s",
    }


@tool("signal_ready")
def signal_ready(dependency: str, data: str) -> Dict[str, Any]:
    """Signal to the swarm that your task is complete or a spec is ready.

    Args:
        dependency: The name of the dependency you are fulfilling (e.g., 'backend_api')
        data: The JSON string or description of the data being shared
    """
    project_id = get_project_id()
    dep_key = f"project:{project_id}:dep:{dependency}"

    # Use a fresh sync Redis connection — thread-safe, no event-loop binding issues
    r = redis.from_url(REDIS_URL, decode_responses=True)

    logger.info(f"[Tool:signal_ready] Signaling: {dependency}")

    r.set(dep_key, data, ex=3600)

    return {
        "status": "success",
        "dependency": dependency,
        "message": f"Successfully signaled {dependency} is ready.",
    }
