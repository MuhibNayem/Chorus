from __future__ import annotations

import json
from typing import Any

EVENT_LOG_LIMIT = 500


def project_event_seq_key(project_id: str) -> str:
    return f"project:{project_id}:events:seq"


def project_event_log_key(project_id: str) -> str:
    return f"project:{project_id}:events:log"


async def append_project_event(
    client: Any,
    project_id: str,
    message: dict[str, Any],
    *,
    ttl_seconds: int = 86400,
    limit: int = EVENT_LOG_LIMIT,
) -> dict[str, Any]:
    if not all(hasattr(client, attr) for attr in ("incr", "rpush", "ltrim", "expire")):
        return dict(message)

    event_id = await client.incr(project_event_seq_key(project_id))
    enriched = dict(message)
    enriched["event_id"] = event_id
    payload = json.dumps(enriched, default=str)
    log_key = project_event_log_key(project_id)
    await client.rpush(log_key, payload)
    await client.ltrim(log_key, -limit, -1)
    await client.expire(log_key, ttl_seconds)
    await client.expire(project_event_seq_key(project_id), ttl_seconds)
    return enriched


async def get_project_events_since(
    client: Any,
    project_id: str,
    *,
    after_event_id: int | None = None,
    limit: int = EVENT_LOG_LIMIT,
) -> list[dict[str, Any]]:
    if not hasattr(client, "lrange"):
        return []

    raw_items = await client.lrange(project_event_log_key(project_id), 0, -1)
    events: list[dict[str, Any]] = []
    for raw_item in raw_items[-limit:]:
        try:
            parsed = json.loads(raw_item)
        except json.JSONDecodeError:
            continue
        try:
            event_id = int(parsed.get("event_id"))
        except (TypeError, ValueError):
            event_id = None
        if after_event_id is not None and event_id is not None and event_id <= after_event_id:
            continue
        events.append(parsed)
    return events
