import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claims import (
    ClaimStatus,
    ClaimType,
    FailureType,
    MAX_RECOVERY_RETRIES,
    build_claim_payload,
)
from src.swarm.claim_store import ClaimStore
from src.swarm.agents import AgentSwarm, CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_WINDOW_SECONDS


# ---------------------------------------------------------------------------
# FakeRedis with sorted-set support (same as test_claim_store.py)
# ---------------------------------------------------------------------------

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


@pytest.fixture
def tmp_project(tmp_path):
    project_id = "test-project"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)
    import src.swarm.tools.workspace_tools as wtools
    orig_base = wtools.WORKSPACE_BASE
    wtools.WORKSPACE_BASE = tmp_path
    yield workspace, project_id
    wtools.WORKSPACE_BASE = orig_base


# ---------------------------------------------------------------------------
# ClaimStore Circuit Breaker Methods
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_agent_violation_increments_count():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    v1 = await store.record_agent_violation("p1", "backend", "evidence_drift", "missing file")
    assert v1["type"] == "evidence_drift"
    assert v1["reason"] == "missing file"

    count = await store.get_agent_violation_count("p1", "backend")
    assert count == 1


@pytest.mark.asyncio
async def test_violation_count_respects_window():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    # Record an old violation with a timestamp well outside the window
    old_ts = "{\"timestamp\": \"2020-01-01T00:00:00Z\", \"type\": \"old\", \"reason\": \"old\"}"
    await redis.zadd(
        store.agent_violations_key("p1", "backend"),
        {old_ts: 1577836800.0},
    )

    # Record a current violation
    await store.record_agent_violation("p1", "backend", "evidence_drift", "new")

    count = await store.get_agent_violation_count("p1", "backend", window_seconds=300)
    assert count == 1  # old violation should be pruned


@pytest.mark.asyncio
async def test_is_agent_circuit_open_false_below_threshold():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
        await store.record_agent_violation("p1", "backend", "evidence_drift")

    assert await store.is_agent_circuit_open("p1", "backend", threshold=CIRCUIT_BREAKER_THRESHOLD) is False


@pytest.mark.asyncio
async def test_is_agent_circuit_open_true_at_threshold():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    for _ in range(CIRCUIT_BREAKER_THRESHOLD):
        await store.record_agent_violation("p1", "backend", "evidence_drift")

    assert await store.is_agent_circuit_open("p1", "backend", threshold=CIRCUIT_BREAKER_THRESHOLD) is True


@pytest.mark.asyncio
async def test_reset_agent_violations_clears_all():
    redis = FakeRedis()
    store = ClaimStore(redis_client=redis)

    for _ in range(5):
        await store.record_agent_violation("p1", "backend", "evidence_drift")

    assert await store.get_agent_violation_count("p1", "backend") == 5
    await store.reset_agent_violations("p1", "backend")
    assert await store.get_agent_violation_count("p1", "backend") == 0


# ---------------------------------------------------------------------------
# AgentSwarm Circuit Breaker + Quarantine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_triggers_after_three_violations(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    class FakeStore:
        def __init__(self):
            self.violations = []

        async def close(self):
            pass

        async def record_agent_violation(self, pid, agent, vtype, reason=""):
            self.violations.append({"type": vtype, "reason": reason})
            return {}

        async def get_agent_violation_count(self, pid, agent, window=300):
            return len(self.violations)

    store = FakeStore()
    swarm.claim_store_factory = lambda: store

    # Record threshold-1 violations — agent should still be allowed
    for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
        await swarm._record_violation("backend", "evidence_drift", "test failure")

    assert swarm._ensure_agent_state("backend")["status"] != "quarantined"

    # One more violation should trip the circuit breaker
    count = await swarm._record_violation("backend", "evidence_drift", "final failure")

    assert count >= CIRCUIT_BREAKER_THRESHOLD
    assert swarm._ensure_agent_state("backend")["status"] == "quarantined"

    # Verify quarantine event was published with violation count
    quarantine_calls = [
        call for call in swarm.blackboard.publish_agent_event.call_args_list
        if call.args[2] == "quarantined"
    ]
    assert len(quarantine_calls) == 1
    assert quarantine_calls[0].args[4]["violation_count"] >= CIRCUIT_BREAKER_THRESHOLD


@pytest.mark.asyncio
async def test_quarantined_agent_blocked_from_running():
    swarm = AgentSwarm()
    swarm.project_id = "test"
    swarm.blackboard = AsyncMock()

    # Mark agent as quarantined
    swarm._ensure_agent_state("backend")["status"] = "quarantined"
    swarm._ensure_agent_state("backend")["inconsistent_reason"] = "Too many failures"

    # _run_single_agent should immediately return False without running
    result = await swarm._run_single_agent("backend", "some task")

    assert result is False

    # Verify error event was published
    error_calls = [
        call for call in swarm.blackboard.publish_agent_event.call_args_list
        if call.args[2] == "error"
    ]
    assert len(error_calls) == 1
    assert "blocked" in error_calls[0].args[3].lower()


@pytest.mark.asyncio
async def test_check_circuit_breaker_blocks_open_circuit(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    store = ClaimStore(redis_client=FakeRedis())
    swarm.claim_store_factory = lambda: store

    # Seed violations directly into the store up to the threshold
    for _ in range(CIRCUIT_BREAKER_THRESHOLD):
        await store.record_agent_violation(project_id, "backend", "evidence_drift")

    allowed, reason = await swarm._check_circuit_breaker("backend")

    assert allowed is False
    assert "circuit breaker open" in reason.lower()
    assert swarm._ensure_agent_state("backend")["status"] == "quarantined"


@pytest.mark.asyncio
async def test_check_circuit_breaker_allows_below_threshold(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    store = ClaimStore(redis_client=FakeRedis())
    swarm.claim_store_factory = lambda: store

    for _ in range(CIRCUIT_BREAKER_THRESHOLD - 1):
        await store.record_agent_violation(project_id, "backend", "evidence_drift")

    allowed, reason = await swarm._check_circuit_breaker("backend")

    assert allowed is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Observability Events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_event_published_to_redis(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    # Create a claim with a workspace revision
    import src.swarm.tools.workspace_tools as wtools
    wtools.WORKSPACE_BASE = workspace.parent
    (workspace / "file.txt").write_text("v1")
    git_hash = wtools.snapshot_workspace(project_id, "test")
    assert git_hash is not None

    (workspace / "file.txt").write_text("v2")

    class FakeStore:
        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            return build_claim_payload(
                project_id=pid,
                claim_type=ct,
                producer_agent="backend",
                status=ClaimStatus.VALID,
                claim_id="runtime-1",
                workspace_revision=git_hash,
            )

        async def record_agent_violation(self, pid, agent, vtype, reason=""):
            return {}

        async def get_agent_violation_count(self, pid, agent, window=300):
            return 1

    swarm.claim_store_factory = lambda: FakeStore()

    async def fake_run(agent_name, task):
        return True

    swarm._run_single_agent = fake_run

    result = await swarm._recover_from_failure(
        ClaimType.BACKEND_RUNTIME_READY.value,
        FailureType.EVIDENCE_DRIFT,
        "Evidence drift detected",
        recovery_attempt=1,
    )

    assert result["status"] == "recovered"

    # Verify claim_recovered event was published
    recovered_calls = [
        call for call in swarm.blackboard.publish_agent_event.call_args_list
        if call.args[2] == "claim_recovered"
    ]
    assert len(recovered_calls) == 1
    data = recovered_calls[0].args[4]
    assert data["claim_type"] == ClaimType.BACKEND_RUNTIME_READY.value
    assert data["failure_type"] == FailureType.EVIDENCE_DRIFT.value
    assert data["recovery_attempt"] == 1


@pytest.mark.asyncio
async def test_verification_failed_event_published(tmp_project):
    workspace, project_id = tmp_project
    from src.swarm.tools.workspace_tools import set_project_context
    set_project_context(project_id)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    class FakeStore:
        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            # Return a claim with evidence that doesn't exist
            return build_claim_payload(
                project_id=pid,
                claim_type=ct,
                producer_agent="backend",
                status=ClaimStatus.VALID,
                claim_id="runtime-1",
                evidence={"files": ["backend/nonexistent.xml"]},
            )

        async def get_claim(self, pid, cid):
            return build_claim_payload(
                project_id=pid,
                claim_type=ClaimType.BACKEND_RUNTIME_READY.value,
                producer_agent="backend",
                status=ClaimStatus.VALID,
                claim_id=cid,
                evidence={"files": ["backend/nonexistent.xml"]},
            )

        async def update_claim_status(self, pid, cid, status, validation=None, reason=""):
            return {}

        async def publish_claim_event(self, pid, event_type, claim, data=None):
            return {"type": event_type}

        async def get_agent_event_seq(self, pid, agent):
            return 1

        async def save_agent_event_seq(self, pid, agent, seq):
            pass

        async def record_agent_violation(self, pid, agent, vtype, reason=""):
            return {}

        async def get_agent_violation_count(self, pid, agent, window=300):
            return 0

    swarm.claim_store_factory = lambda: FakeStore()

    # Mock _run_single_agent so recovery succeeds but claim stays invalid
    async def fake_run(agent_name, task):
        return True

    swarm._run_single_agent = fake_run

    ok, error = await swarm._ensure_valid_claim_with_recovery(
        ClaimType.BACKEND_RUNTIME_READY.value, publish_if_missing=False
    )

    assert ok is False

    # Verify verification_failed events were published
    failed_calls = [
        call for call in swarm.blackboard.publish_agent_event.call_args_list
        if call.args[2] == "verification_failed"
    ]
    assert len(failed_calls) >= 1
    data = failed_calls[0].args[4]
    assert data["claim_type"] == ClaimType.BACKEND_RUNTIME_READY.value
    assert "failure_type" in data
    assert "attempt" in data


@pytest.mark.asyncio
async def test_quarantine_event_includes_violation_count(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    class FakeStore:
        def __init__(self):
            self.violation_count = 2

        async def close(self):
            pass

        async def get_agent_violation_count(self, pid, agent, window=300):
            return self.violation_count

        async def update_claim_status(self, pid, cid, status, validation=None, reason=""):
            return {}

        async def publish_claim_event(self, pid, event_type, claim, data=None):
            return {"type": event_type}

        async def get_latest_claim(self, pid, ct):
            return None

    swarm.claim_store_factory = lambda: FakeStore()

    await swarm._quarantine_agent("backend", "Test quarantine")

    quarantine_calls = [
        call for call in swarm.blackboard.publish_agent_event.call_args_list
        if call.args[2] == "quarantined"
    ]
    assert len(quarantine_calls) == 1
    data = quarantine_calls[0].args[4]
    assert data["violation_count"] == 2
    assert data["circuit_breaker_threshold"] == CIRCUIT_BREAKER_THRESHOLD
    assert data["circuit_breaker_window_seconds"] == CIRCUIT_BREAKER_WINDOW_SECONDS
