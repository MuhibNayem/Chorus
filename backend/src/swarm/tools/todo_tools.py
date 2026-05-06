"""Todo list tools for agent-authored dynamic task tracking.

Agents call write_todos() to set their plan, and update_todo_status() to mark
steps complete. Todos are stored in Redis and streamed to the frontend via SSE
state events. This replaces hardcoded frontend task lists with agent-authored
plans that adapt to the actual work being done.
"""

import json
import logging
import os
from typing import Dict, Any, List, Optional
from contextvars import ContextVar
from langchain_core.tools import tool
import redis.asyncio as redis

from .workspace_tools import get_project_id

logger = logging.getLogger("tools")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Thread-local / async-safe project context
_agent_name_var: ContextVar[Optional[str]] = ContextVar("agent_name", default=None)

# Local todo cache (fallback)
_agent_todos: Dict[str, List[Dict[str, Any]]] = {}


def set_agent_name(agent_name: str):
    """Set the current agent name in context for todo tools."""
    _agent_name_var.set(agent_name)


def get_agent_name() -> str:
    """Get the current agent name from context, or fallback to thread name."""
    name = _agent_name_var.get()
    if name:
        return name
    # Fallback: try to extract from thread name
    import threading
    thread_name = threading.current_thread().name
    for known in ("rootdep", "backend", "frontend", "devops", "packager"):
        if known in thread_name.lower():
            return known
    return "unknown"


def _get_todo_key(project_id: str, agent_name: str) -> str:
    return f"project:{project_id}:agent:{agent_name}:todos"


async def _publish_state_event(project_id: str, agent_name: str, todos: List[Dict[str, Any]]):
    """Publish a state event to Redis so the frontend receives the updated todos."""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        channel = f"project:{project_id}:events"
        message = {
            "agent_name": agent_name,
            "agent_id": f"agent-{agent_name.lower()}",
            "type": "state",
            "content": f"{agent_name} updated todo list ({sum(1 for t in todos if t['status'] == 'completed')}/{len(todos)} done)",
            "data": {"todos": todos},
            "timestamp": int(__import__('datetime').datetime.now().timestamp() * 1000),
        }
        await r.publish(channel, json.dumps(message, default=str))
    except Exception as e:
        logger.warning(f"[todo_tools] Failed to publish state event: {e}")
    finally:
        await r.aclose()


@tool("write_todos")
async def write_todos(todos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Set your current task plan / todo list.

    Call this BEFORE starting work to declare what steps you will take.
    Each todo must have:
      - content: str  (human-readable task description)
      - status: str   ("pending", "in_progress", or "completed")

    Example:
        write_todos([
            {"content": "Read project specification", "status": "pending"},
            {"content": "Generate Spring Boot backend code", "status": "pending"},
            {"content": "Signal completion to frontend agent", "status": "pending"}
        ])

    Update individual items later with update_todo_status().
    """
    project_id = get_project_id()
    agent_name = get_agent_name()

    # Validate todo structure
    validated = []
    for i, t in enumerate(todos):
        content = t.get("content", f"Task {i+1}")
        status = t.get("status", "pending")
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        validated.append({"content": content, "status": status})

    # Store in Redis
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        key = _get_todo_key(project_id, agent_name)
        await r.set(key, json.dumps(validated), ex=3600)
    except Exception as e:
        logger.warning(f"[write_todos] Redis store failed: {e}")
    finally:
        await r.aclose()

    # Also cache locally
    cache_key = f"{project_id}:{agent_name}"
    _agent_todos[cache_key] = validated

    # Publish state event for frontend
    await _publish_state_event(project_id, agent_name, validated)

    completed = sum(1 for t in validated if t["status"] == "completed")
    logger.info(f"[write_todos] {agent_name}: {completed}/{len(validated)} tasks planned")

    return {
        "status": "success",
        "agent": agent_name,
        "todos_count": len(validated),
        "completed": completed,
        "todos": validated,
    }


@tool("update_todo_status")
async def update_todo_status(index: int, status: str) -> Dict[str, Any]:
    """Update the status of a todo item by its index.

    Args:
        index: 0-based index of the todo item to update
        status: New status — "in_progress" or "completed"

    Call this after starting or finishing each step in your plan.

    Example:
        update_todo_status(0, "completed")  # Mark first task as done
        update_todo_status(1, "in_progress")  # Mark second task as active
    """
    project_id = get_project_id()
    agent_name = get_agent_name()

    if status not in ("pending", "in_progress", "completed"):
        return {"status": "error", "error": f"Invalid status: {status}. Use pending/in_progress/completed."}

    # Try to load existing todos from Redis
    todos = []
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        key = _get_todo_key(project_id, agent_name)
        raw = await r.get(key)
        if raw:
            todos = json.loads(raw)
    except Exception as e:
        logger.warning(f"[update_todo_status] Redis load failed: {e}")
    finally:
        await r.aclose()

    # Fallback to local cache
    if not todos:
        cache_key = f"{project_id}:{agent_name}"
        todos = _agent_todos.get(cache_key, [])

    if not todos:
        return {"status": "error", "error": "No todo list found. Call write_todos() first."}

    if index < 0 or index >= len(todos):
        return {"status": "error", "error": f"Invalid index {index}. List has {len(todos)} items."}

    old_status = todos[index]["status"]
    todos[index]["status"] = status

    # Store updated list back to Redis
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        key = _get_todo_key(project_id, agent_name)
        await r.set(key, json.dumps(todos), ex=3600)
    except Exception as e:
        logger.warning(f"[update_todo_status] Redis store failed: {e}")
    finally:
        await r.aclose()

    # Update local cache
    cache_key = f"{project_id}:{agent_name}"
    _agent_todos[cache_key] = todos

    # Publish state event for frontend
    await _publish_state_event(project_id, agent_name, todos)

    completed = sum(1 for t in todos if t["status"] == "completed")
    logger.info(f"[update_todo_status] {agent_name}: task {index} {old_status}→{status} ({completed}/{len(todos)} done)")

    return {
        "status": "success",
        "agent": agent_name,
        "index": index,
        "old_status": old_status,
        "new_status": status,
        "todos": todos,
    }
