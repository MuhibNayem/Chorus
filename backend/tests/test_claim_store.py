import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claim_store import ClaimNotFoundError, ClaimStore
from src.swarm.claims import ClaimStatus, ClaimType, build_claim_payload


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}
        self.zsets: dict[str, list[tuple[float, str]]] = {}
        self.published = []
        self.ping_count = 0
        self.closed = False

    async def ping(self):
        self.ping_count += 1
        return True

    async def aclose(self):
        self.closed = True

    async def set(self, key, value, ex=None):
        self.values[key] = {"value": value, "ex": ex}
        return True

    async def get(self, key):
        entry = self.values.get(key)
        return entry["value"] if entry else None

    async def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    async def zadd(self, key, mapping):
        # mapping: {member: score}
        entries = self.zsets.setdefault(key, [])
        for member, score in mapping.items():
            entries.append((float(score), str(member)))
        return len(mapping)

    async def zremrangebyscore(self, key, min_score, max_score):
        entries = self.zsets.get(key, [])
        if not entries:
            return 0
        min_val = float("-inf") if min_score == "-inf" else float(min_score)
        max_val = float("inf") if max_score == "+inf" else float(max_score)
        removed = sum(1 for s, _ in entries if min_val <= s <= max_val)
        self.zsets[key] = [(s, m) for s, m in entries if not (min_val <= s <= max_val)]
        return removed

    async def zcard(self, key):
        return len(self.zsets.get(key, []))

    async def zrange(self, key, start, end):
        entries = self.zsets.get(key, [])
        if end == -1:
            end = None
        else:
            end = end + 1
        return [m for _, m in entries[start:end]]

    async def expire(self, key, seconds):
        return True


def make_claim(claim_type=ClaimType.BACKEND_API_READY, claim_id="claim-1"):
    return build_claim_payload(
        project_id="project-1",
        claim_type=claim_type,
        producer_agent="backend",
        evidence={"files": ["backend/API_MANIFEST.json"]},
        claim_id=claim_id,
        now="2026-05-07T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_save_and_get_claim_round_trip():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis, ttl_seconds=123)
    claim = make_claim()

    await store.save_claim("project-1", claim)
    loaded = await store.get_claim("project-1", "claim-1")

    assert loaded == claim
    assert redis.values[store.claim_key("project-1", "claim-1")]["ex"] == 123
    assert "claim-1" in redis.sets[store.claim_index_key("project-1")]


@pytest.mark.asyncio
async def test_latest_claim_lookup():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)
    first = make_claim(claim_id="claim-1")
    second = make_claim(claim_id="claim-2")

    await store.save_claim("project-1", first)
    await store.save_claim("project-1", second)

    latest = await store.get_latest_claim("project-1", ClaimType.BACKEND_API_READY.value)

    assert latest["id"] == "claim-2"


@pytest.mark.asyncio
async def test_get_latest_claim_returns_none_when_missing():
    store = ClaimStore(redis_client=FakeRedis())

    assert await store.get_latest_claim("project-1", "SPEC_READY") is None


@pytest.mark.asyncio
async def test_list_claim_ids():
    store = ClaimStore(redis_client=FakeRedis())
    await store.save_claim("project-1", make_claim(claim_id="claim-1"))
    await store.save_claim("project-1", make_claim(claim_id="claim-2"))

    assert await store.list_claim_ids("project-1") == {"claim-1", "claim-2"}


@pytest.mark.asyncio
async def test_update_claim_status_preserves_claim_data_and_validation():
    store = ClaimStore(redis_client=FakeRedis())
    claim = make_claim()
    await store.save_claim("project-1", claim)

    updated = await store.update_claim_status(
        "project-1",
        "claim-1",
        ClaimStatus.VALID,
        {
            "status": "valid",
            "validated_at": "2026-05-07T00:01:00Z",
            "errors": [],
            "warnings": ["warning-1"],
        },
    )

    assert updated["status"] == "valid"
    assert updated["id"] == claim["id"]
    assert updated["evidence"] == claim["evidence"]
    assert updated["depends_on"] == claim["depends_on"]
    assert updated["validation"] == {
        "status": "valid",
        "validated_at": "2026-05-07T00:01:00Z",
        "errors": [],
        "warnings": ["warning-1"],
    }
    assert updated["updated_at"] != claim["updated_at"]


@pytest.mark.asyncio
async def test_update_claim_status_keeps_default_validation_lists():
    store = ClaimStore(redis_client=FakeRedis())
    await store.save_claim("project-1", make_claim())

    updated = await store.update_claim_status(
        "project-1",
        "claim-1",
        "invalid",
        {"status": "invalid"},
    )

    assert updated["validation"]["errors"] == []
    assert updated["validation"]["warnings"] == []


@pytest.mark.asyncio
async def test_publish_claim_event_shape():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)
    claim = make_claim()

    event = await store.publish_claim_event(
        "project-1",
        "claim_validated",
        claim,
        {"extra": "value"},
    )

    assert redis.published[0][0] == "project:project-1:events"
    published = json.loads(redis.published[0][1])
    assert published == event
    assert event["agent_name"] == "backend"
    assert event["agent_id"] == "agent-backend"
    assert event["type"] == "claim_validated"
    assert event["content"] == "BACKEND_API_READY is claimed"
    assert event["data"] == {
        "claim_id": "claim-1",
        "claim_type": "BACKEND_API_READY",
        "claim_status": "claimed",
        "producer_agent": "backend",
        "extra": "value",
    }
    assert event["timestamp"].endswith("Z")


@pytest.mark.asyncio
async def test_get_claim_raises_for_missing_claim():
    store = ClaimStore(redis_client=FakeRedis())

    with pytest.raises(ClaimNotFoundError):
        await store.get_claim("project-1", "missing")


@pytest.mark.asyncio
async def test_save_claim_rejects_project_mismatch():
    store = ClaimStore(redis_client=FakeRedis())
    claim = make_claim()

    with pytest.raises(ValueError, match="project_id mismatch"):
        await store.save_claim("other-project", claim)


@pytest.mark.asyncio
async def test_save_claim_rejects_missing_identity_fields():
    store = ClaimStore(redis_client=FakeRedis())
    claim = make_claim()
    del claim["claim_type"]

    with pytest.raises(ValueError, match="missing required identity"):
        await store.save_claim("project-1", claim)


def test_key_helpers():
    assert ClaimStore.claim_index_key("p") == "project:p:claims:index"
    assert ClaimStore.latest_claim_key("p", "SPEC_READY") == "project:p:claims:SPEC_READY"
    assert ClaimStore.claim_key("p", "claim-1") == "project:p:claim:claim-1"
    assert ClaimStore.claim_dependencies_key("p", "claim-1") == "project:p:claim_dependencies:claim-1"
    assert ClaimStore.events_channel("p") == "project:p:events"
    assert ClaimStore.agent_event_seq_key("p", "backend") == "project:p:agent:backend:event_seq"
    assert ClaimStore.agent_last_activity_key("p", "backend") == "project:p:agent:backend:last_activity_at"


@pytest.mark.asyncio
async def test_save_and_get_agent_event_seq():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)
    await store.save_agent_event_seq("project-1", "backend", 42)
    assert await store.get_agent_event_seq("project-1", "backend") == 42


@pytest.mark.asyncio
async def test_get_agent_event_seq_returns_none_when_missing():
    store = ClaimStore(redis_client=FakeRedis())
    assert await store.get_agent_event_seq("project-1", "backend") is None


@pytest.mark.asyncio
async def test_save_agent_last_activity():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)
    await store.save_agent_last_activity("project-1", "backend")
    raw = redis.values.get(store.agent_last_activity_key("project-1", "backend"))
    assert raw is not None
    assert raw["value"].endswith("Z")


@pytest.mark.asyncio
async def test_get_claims_by_type():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)
    c1 = make_claim(claim_type=ClaimType.BACKEND_API_READY, claim_id="c1")
    c2 = make_claim(claim_type=ClaimType.BACKEND_RUNTIME_READY, claim_id="c2")
    c3 = make_claim(claim_type=ClaimType.BACKEND_API_READY, claim_id="c3")
    await store.save_claim("project-1", c1)
    await store.save_claim("project-1", c2)
    await store.save_claim("project-1", c3)

    api_claims = await store.get_claims_by_type("project-1", ClaimType.BACKEND_API_READY.value)
    assert len(api_claims) == 2
    assert {c["id"] for c in api_claims} == {"c1", "c3"}

    runtime_claims = await store.get_claims_by_type("project-1", ClaimType.BACKEND_RUNTIME_READY.value)
    assert len(runtime_claims) == 1
    assert runtime_claims[0]["id"] == "c2"


@pytest.mark.asyncio
async def test_update_claim_status_with_reason():
    store = ClaimStore(redis_client=FakeRedis())
    claim = make_claim()
    await store.save_claim("project-1", claim)

    updated = await store.update_claim_status(
        "project-1", "claim-1", ClaimStatus.STALE, reason="producer wrote files after claim"
    )

    assert updated["status"] == "stale"
    assert "producer wrote files after claim" in updated["validation"]["errors"]


@pytest.mark.asyncio
async def test_connect_and_close_with_injected_client():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    await store.connect()
    await store.close()

    assert redis.ping_count == 1
    assert not redis.closed
    assert store._redis is None
