"""Redis-backed storage for swarm readiness claims."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol

import redis.asyncio as redis

from ..blackboard.event_log import append_project_event
from .claims import ClaimStatus, claim_now_iso

logger = logging.getLogger("claim_store")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CLAIM_TTL_SECONDS = int(os.getenv("SWARM_CLAIM_TTL_SECONDS", "86400"))


class RedisLike(Protocol):
    async def ping(self) -> Any: ...
    async def aclose(self) -> Any: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> Any: ...
    async def get(self, key: str) -> str | None: ...
    async def sadd(self, key: str, *values: str) -> Any: ...
    async def smembers(self, key: str) -> set[str]: ...
    async def publish(self, channel: str, message: str) -> Any: ...
    async def zadd(self, key: str, mapping: dict[str, Any]) -> Any: ...
    async def zremrangebyscore(self, key: str, min_score: str, max_score: str) -> Any: ...
    async def zcard(self, key: str) -> int: ...
    async def zrange(self, key: str, start: int, end: int) -> list[Any]: ...
    async def expire(self, key: str, seconds: int) -> Any: ...


class ClaimNotFoundError(KeyError):
    pass


class ClaimStore:
    def __init__(
        self,
        redis_url: str = REDIS_URL,
        *,
        redis_client: RedisLike | None = None,
        ttl_seconds: int = CLAIM_TTL_SECONDS,
    ):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._redis: RedisLike | None = redis_client
        self._owns_client = redis_client is None

    async def connect(self):
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()

    async def close(self):
        if self._redis and self._owns_client:
            await self._redis.aclose()
        self._redis = None

    async def save_claim(self, project_id: str, claim: dict[str, Any]) -> dict[str, Any]:
        self._validate_claim_identity(project_id, claim)
        client = await self._client()
        claim_id = claim["id"]
        claim_type = claim["claim_type"]
        payload = json.dumps(claim, default=str)

        await client.set(self.claim_key(project_id, claim_id), payload, ex=self.ttl_seconds)
        await client.sadd(self.claim_index_key(project_id), claim_id)
        await client.set(self.latest_claim_key(project_id, claim_type), claim_id, ex=self.ttl_seconds)

        return claim

    async def get_claim(self, project_id: str, claim_id: str) -> dict[str, Any]:
        client = await self._client()
        raw = await client.get(self.claim_key(project_id, claim_id))
        if not raw:
            raise ClaimNotFoundError(f"Claim not found: {claim_id}")
        return self._loads_claim(raw)

    async def get_latest_claim(self, project_id: str, claim_type: str) -> dict[str, Any] | None:
        client = await self._client()
        claim_id = await client.get(self.latest_claim_key(project_id, claim_type))
        if not claim_id:
            return None
        return await self.get_claim(project_id, claim_id)

    async def list_claim_ids(self, project_id: str) -> set[str]:
        client = await self._client()
        return set(await client.smembers(self.claim_index_key(project_id)))

    async def update_claim_status(
        self,
        project_id: str,
        claim_id: str,
        status: str | ClaimStatus,
        validation: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        claim = await self.get_claim(project_id, claim_id)
        claim["status"] = status.value if isinstance(status, ClaimStatus) else str(status)
        claim["updated_at"] = claim_now_iso()

        if validation is not None:
            existing = dict(claim.get("validation") or {})
            existing.update(validation)
            existing.setdefault("errors", [])
            existing.setdefault("warnings", [])
            claim["validation"] = existing

        if reason:
            claim_validation = dict(claim.get("validation") or {})
            claim_validation.setdefault("errors", [])
            if reason not in claim_validation["errors"]:
                claim_validation["errors"].append(reason)
            claim["validation"] = claim_validation

        await self.save_claim(project_id, claim)
        return claim

    async def publish_claim_event(
        self,
        project_id: str,
        event_type: str,
        claim: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._client()
        event_data = {
            "claim_id": claim["id"],
            "claim_type": claim["claim_type"],
            "claim_status": claim["status"],
            "producer_agent": claim["producer_agent"],
        }
        if data:
            event_data.update(data)

        message = {
            "agent_name": claim["producer_agent"],
            "agent_id": f"agent-{claim['producer_agent'].lower()}",
            "type": event_type,
            "content": f"{claim['claim_type']} is {claim['status']}",
            "data": event_data,
            "timestamp": claim_now_iso(),
        }
        message = await append_project_event(
            client,
            project_id,
            message,
            ttl_seconds=self.ttl_seconds,
        )
        await client.publish(self.events_channel(project_id), json.dumps(message, default=str))
        return message

    @staticmethod
    def claim_index_key(project_id: str) -> str:
        return f"project:{project_id}:claims:index"

    @staticmethod
    def latest_claim_key(project_id: str, claim_type: str) -> str:
        return f"project:{project_id}:claims:{claim_type}"

    @staticmethod
    def claim_key(project_id: str, claim_id: str) -> str:
        return f"project:{project_id}:claim:{claim_id}"

    @staticmethod
    def claim_dependencies_key(project_id: str, claim_id: str) -> str:
        return f"project:{project_id}:claim_dependencies:{claim_id}"

    @staticmethod
    def events_channel(project_id: str) -> str:
        return f"project:{project_id}:events"

    @staticmethod
    def agent_event_seq_key(project_id: str, agent_name: str) -> str:
        return f"project:{project_id}:agent:{agent_name}:event_seq"

    @staticmethod
    def agent_last_activity_key(project_id: str, agent_name: str) -> str:
        return f"project:{project_id}:agent:{agent_name}:last_activity_at"

    async def save_agent_event_seq(self, project_id: str, agent_name: str, event_seq: int) -> None:
        client = await self._client()
        await client.set(self.agent_event_seq_key(project_id, agent_name), str(event_seq), ex=self.ttl_seconds)

    async def get_agent_event_seq(self, project_id: str, agent_name: str) -> int | None:
        client = await self._client()
        raw = await client.get(self.agent_event_seq_key(project_id, agent_name))
        return int(raw) if raw is not None else None

    async def save_agent_last_activity(self, project_id: str, agent_name: str) -> None:
        client = await self._client()
        await client.set(self.agent_last_activity_key(project_id, agent_name), claim_now_iso(), ex=self.ttl_seconds)

    # -----------------------------------------------------------------------
    # Phase 5: Circuit Breaker — Agent Violation Tracking
    # -----------------------------------------------------------------------

    @staticmethod
    def agent_violations_key(project_id: str, agent_name: str) -> str:
        return f"project:{project_id}:agent:{agent_name}:violations"

    async def record_agent_violation(
        self,
        project_id: str,
        agent_name: str,
        violation_type: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Record a violation for an agent. Returns the violation entry."""
        client = await self._client()
        from datetime import datetime, timezone
        timestamp_iso = claim_now_iso()
        timestamp_score = datetime.now(timezone.utc).timestamp()
        violation = json.dumps({
            "timestamp": timestamp_iso,
            "type": violation_type,
            "reason": reason,
        }, default=str)
        # Use a sorted set with Unix timestamp as score for efficient window queries
        await client.zadd(
            self.agent_violations_key(project_id, agent_name),
            {violation: timestamp_score},
        )
        # Expire the whole set with TTL so old violations auto-clean
        await client.expire(
            self.agent_violations_key(project_id, agent_name),
            self.ttl_seconds,
        )
        return {"timestamp": timestamp_iso, "type": violation_type, "reason": reason}

    async def get_agent_violation_count(
        self,
        project_id: str,
        agent_name: str,
        window_seconds: int = 300,
    ) -> int:
        """Count violations within the last *window_seconds*."""
        client = await self._client()
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).timestamp()
        # Remove entries older than the window first
        await client.zremrangebyscore(
            self.agent_violations_key(project_id, agent_name),
            "-inf",
            str(cutoff),
        )
        # Count remaining entries
        count = await client.zcard(
            self.agent_violations_key(project_id, agent_name)
        )
        return count

    async def get_agent_violations(
        self,
        project_id: str,
        agent_name: str,
        window_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        """Return all violations within the last *window_seconds*."""
        client = await self._client()
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).timestamp()
        await client.zremrangebyscore(
            self.agent_violations_key(project_id, agent_name),
            "-inf",
            str(cutoff),
        )
        raw_violations = await client.zrange(
            self.agent_violations_key(project_id, agent_name),
            0,
            -1,
        )
        violations: list[dict[str, Any]] = []
        for raw in raw_violations:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                violations.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return violations

    async def reset_agent_violations(
        self,
        project_id: str,
        agent_name: str,
    ) -> bool:
        """Clear all recorded violations for an agent."""
        client = await self._client()
        await client.zremrangebyscore(
            self.agent_violations_key(project_id, agent_name),
            "-inf",
            "+inf",
        )
        return True

    async def is_agent_circuit_open(
        self,
        project_id: str,
        agent_name: str,
        threshold: int = 3,
        window_seconds: int = 300,
    ) -> bool:
        """Return True if the agent has >= *threshold* violations in *window_seconds*."""
        count = await self.get_agent_violation_count(
            project_id, agent_name, window_seconds
        )
        return count >= threshold

    async def delete_project_claims(self, project_id: str) -> int:
        """Delete all claim-related Redis keys for a project. Returns count of deleted keys."""
        client = await self._client()
        deleted = 0
        cursor = 0
        pattern = f"project:{project_id}:*"
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        return deleted

    async def get_claims_by_type(self, project_id: str, claim_type: str) -> list[dict[str, Any]]:
        """Return all historical claims for a given type."""
        client = await self._client()
        claim_ids = await self.list_claim_ids(project_id)
        claims: list[dict[str, Any]] = []
        for claim_id in claim_ids:
            try:
                claim = await self.get_claim(project_id, claim_id)
                if claim.get("claim_type") == claim_type:
                    claims.append(claim)
            except ClaimNotFoundError:
                continue
        return claims

    async def get_valid_claims_by_type(self, project_id: str, claim_type: str) -> list[dict[str, Any]]:
        """Return all VALID claims for a given type."""
        from .claims import ClaimStatus
        all_claims = await self.get_claims_by_type(project_id, claim_type)
        return [c for c in all_claims if c.get("status") == ClaimStatus.VALID.value]

    async def _client(self) -> RedisLike:
        if self._redis is None:
            await self.connect()
        if self._redis is None:
            raise RuntimeError("ClaimStore Redis client is not initialized")
        return self._redis

    @staticmethod
    def _loads_claim(raw: str | bytes | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Stored claim payload is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Stored claim payload must be a JSON object")
        return value

    @staticmethod
    def _validate_claim_identity(project_id: str, claim: dict[str, Any]):
        missing = [key for key in ("id", "project_id", "claim_type") if not claim.get(key)]
        if missing:
            raise ValueError(f"Claim missing required identity fields: {', '.join(missing)}")
        if claim["project_id"] != project_id:
            raise ValueError(
                f"Claim project_id mismatch: expected {project_id}, got {claim['project_id']}"
            )
