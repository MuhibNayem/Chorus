"""User directive tool — lets users send mid-run instructions to a running agent,
pause a specific agent for input, and stop the entire swarm.

Three flows:

1. Soft directive (non-blocking)
   User → POST /api/projects/{id}/directive → Redis key
   Agent → poll_user_directive() at checkpoint → reads+clears key → adapts

2. Pause/resume (blocking at checkpoint)
   User → POST /api/projects/{id}/agents/{name}/pause  → directive key = "__PAUSE__: msg"
   Agent → poll_user_directive() sees __PAUSE__ → publishes agent_paused SSE → blocks
   User → POST /api/projects/{id}/agents/{name}/resume → resume key = user input
   Agent unblocks → receives "Pause context: ... / User resumed with: ..." → continues

3. Swarm stop (checked every poll cycle inside pause, and in execute_parallel)
   User → POST /api/projects/{id}/swarm/stop
   Any paused agent unblocks with a stop signal; execute_parallel aborts between steps.

Redis keys:
  directive  : project:{id}:directive:{agent}      SETEX 1h  written by /directive or /pause
  resume     : project:{id}:agent:{agent}:resume   SETEX 1h  written by /resume
  swarm_stop : project:{id}:swarm:stop             SETEX 24h written by /swarm/stop
"""

import json
import logging
import os
import asyncio

import redis.asyncio as redis
from langchain_core.tools import tool

from .workspace_tools import get_project_id, _agent_name_var

logger = logging.getLogger("tools")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PAUSE_TIMEOUT_SECONDS = int(os.getenv("AGENT_PAUSE_TIMEOUT_SECONDS", "1800"))  # 30 min
PAUSE_POLL_INTERVAL = 2.0

PAUSE_PREFIX = "__PAUSE__:"


def directive_redis_key(project_id: str, agent_name: str) -> str:
    return f"project:{project_id}:directive:{agent_name}"


def resume_redis_key(project_id: str, agent_name: str) -> str:
    return f"project:{project_id}:agent:{agent_name}:resume"


def swarm_stop_redis_key(project_id: str) -> str:
    return f"project:{project_id}:swarm:stop"


async def is_swarm_stopped(project_id: str) -> bool:
    """Non-blocking check used by execute_parallel between agent steps."""
    r: redis.Redis | None = None
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        return bool(await r.exists(swarm_stop_redis_key(project_id)))
    except Exception:
        return False
    finally:
        if r is not None:
            await r.aclose()


@tool
async def poll_user_directive() -> str:
    """Check whether the user has sent a directive, pause request, or stop signal.

    Call this at every natural checkpoint (after each verify_progress, after
    each batch of file writes). It returns immediately unless the user paused
    this agent — in that case it blocks until the user resumes or times out.

    Returns one of:
    - Empty string — nothing pending, continue normally.
    - A directive string — incorporate it and continue.
    - "SWARM_STOPPED" — stop all work immediately and do not publish any claims.
    - A pause+resume message — user paused then resumed with new input; incorporate it.
    """
    project_id = get_project_id()
    agent_name = _agent_name_var.get() or "unknown"

    if not project_id:
        return ""

    r: redis.Redis | None = None
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)

        # Always check swarm stop first
        if await r.exists(swarm_stop_redis_key(project_id)):
            logger.info("[poll_user_directive] Swarm stop detected for agent=%s", agent_name)
            return "SWARM_STOPPED"

        key = directive_redis_key(project_id, agent_name)
        directive = await r.getdel(key)

        if not directive:
            return ""

        channel = f"project:{project_id}:events"

        # --- Pause flow ---
        if directive.startswith(PAUSE_PREFIX):
            pause_message = directive[len(PAUSE_PREFIX):].strip()
            logger.info("[poll_user_directive] Agent %s paused: %s", agent_name, pause_message[:80])

            await r.publish(channel, json.dumps({
                "type": "agent_paused",
                "data": {"agent": agent_name, "message": pause_message},
            }))

            resume_key = resume_redis_key(project_id, agent_name)
            stop_key = swarm_stop_redis_key(project_id)
            elapsed = 0.0

            while elapsed < PAUSE_TIMEOUT_SECONDS:
                # Check swarm stop
                if await r.exists(stop_key):
                    logger.info("[poll_user_directive] Swarm stopped while agent %s was paused", agent_name)
                    await r.publish(channel, json.dumps({
                        "type": "agent_stopped",
                        "data": {"agent": agent_name, "reason": "swarm_stop"},
                    }))
                    return "SWARM_STOPPED"

                # Check resume
                resume_input = await r.getdel(resume_key)
                if resume_input is not None:
                    logger.info("[poll_user_directive] Agent %s resumed", agent_name)
                    await r.publish(channel, json.dumps({
                        "type": "agent_resumed",
                        "data": {"agent": agent_name, "input": resume_input},
                    }))
                    return (
                        f"Pause context: {pause_message}\n"
                        f"User resumed with: {resume_input}"
                    )

                await asyncio.sleep(PAUSE_POLL_INTERVAL)
                elapsed += PAUSE_POLL_INTERVAL

            # Timeout — auto-resume with warning
            timeout_msg = f"Pause timed out after {PAUSE_TIMEOUT_SECONDS}s — resuming automatically."
            logger.warning("[poll_user_directive] %s agent=%s", timeout_msg, agent_name)
            await r.publish(channel, json.dumps({
                "type": "agent_resumed",
                "data": {"agent": agent_name, "reason": "timeout", "input": timeout_msg},
            }))
            return f"Pause context: {pause_message}\nUser resumed with: {timeout_msg}"

        # --- Soft directive ---
        logger.info("[poll_user_directive] Directive for agent=%s: %s", agent_name, directive[:120])
        await r.publish(channel, json.dumps({
            "type": "directive_received",
            "data": {"agent": agent_name, "directive": directive},
        }))
        return directive

    except Exception as exc:
        logger.warning("[poll_user_directive] Error: %s", exc)
        return ""
    finally:
        if r is not None:
            await r.aclose()
