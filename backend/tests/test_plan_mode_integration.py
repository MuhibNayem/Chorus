import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm import agents as agents_module
from src.swarm.agents import AgentSwarm
from src.swarm.claims import ClaimType


class FakeClaimStore:
    def __init__(self):
        self.claims = {}
        self.latest = {}
        self.published = []
        self.seq = {}

    async def connect(self):
        pass

    async def close(self):
        pass

    async def save_claim(self, project_id, claim):
        self.claims[claim["id"]] = claim
        self.latest[claim["claim_type"]] = claim["id"]
        return claim

    async def get_claim(self, project_id, claim_id):
        if claim_id not in self.claims:
            raise KeyError(f"Claim not found: {claim_id}")
        return self.claims[claim_id]

    async def get_latest_claim(self, project_id, claim_type):
        claim_id = self.latest.get(claim_type)
        if not claim_id:
            return None
        return self.claims.get(claim_id)

    async def update_claim_status(self, project_id, claim_id, status, validation=None, reason=""):
        claim = self.claims[claim_id]
        claim["status"] = status.value if hasattr(status, "value") else str(status)
        if validation is not None:
            claim.setdefault("validation", {})
            claim["validation"].update(validation)
        if reason:
            claim.setdefault("validation", {})
            claim["validation"].setdefault("errors", [])
            if reason not in claim["validation"]["errors"]:
                claim["validation"]["errors"].append(reason)
        return claim

    async def publish_claim_event(self, project_id, event_type, claim, data=None):
        self.published.append((event_type, claim, data))
        return {"type": event_type}

    async def save_agent_event_seq(self, project_id, agent_name, seq):
        self.seq[agent_name] = seq

    async def get_agent_event_seq(self, project_id, agent_name):
        return self.seq.get(agent_name)

    async def save_agent_last_activity(self, project_id, agent_name):
        pass

    async def list_claim_ids(self, project_id):
        return set(self.claims.keys())

    async def get_agent_violation_count(self, project_id, agent_name, window=300):
        return 0

    async def record_agent_violation(self, project_id, agent_name, vtype, reason=""):
        return {}


# ---------------------------------------------------------------------------
# Plan Mode Integration Tests
# ---------------------------------------------------------------------------

def test_plan_mode_publishes_spec_ready_and_returns_complete(monkeypatch, tmp_path):
    """Plan mode: RootDep runs, SPEC.md exists, SPEC_READY claim validates, returns complete."""
    project_id = "plan-success-project"
    workspace = tmp_path / project_id
    workspace.mkdir()
    (workspace / "SPEC.md").write_text("# Spec")

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "plan"
    swarm.agents = {"rootdep": object()}

    fake_store = FakeClaimStore()
    swarm.claim_store_factory = lambda: fake_store

    calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append(agent_name)
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    async def fake_publish(*args, **kwargs):
        return True

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)
    monkeypatch.setattr(swarm, "_publish_agent_event", fake_publish)
    monkeypatch.setattr(swarm.blackboard, "publish_agent_event", fake_publish)

    result = asyncio.run(swarm.execute_parallel({"rootdep": ["Write a spec"]}))

    assert result["status"] == "complete"
    assert calls == ["rootdep"]
    # SPEC_READY claim should have been auto-published and validated
    assert ClaimType.SPEC_READY.value in fake_store.latest
    claim = fake_store.claims[fake_store.latest[ClaimType.SPEC_READY.value]]
    assert claim["claim_type"] == ClaimType.SPEC_READY.value
    assert claim["producer_agent"] == "rootdep"


def test_plan_mode_retries_rootdep_on_invalid_spec(monkeypatch, tmp_path):
    """Plan mode: first SPEC_READY validation fails, retry succeeds."""
    project_id = "plan-retry-project"
    workspace = tmp_path / project_id
    workspace.mkdir()

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "plan"
    swarm.agents = {"rootdep": object()}

    calls = []
    ensure_calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append((agent_name, task))
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    async def fake_publish(*args, **kwargs):
        return True

    # Mock _ensure_valid_claims to fail once, then succeed
    async def fake_ensure_valid_claims(claim_types, publish_if_missing=True):
        ensure_calls.append("call")
        if len(ensure_calls) == 1:
            return "SPEC_READY is not valid: evidence missing"
        return ""

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)
    monkeypatch.setattr(swarm, "_publish_agent_event", fake_publish)
    monkeypatch.setattr(swarm.blackboard, "publish_agent_event", fake_publish)
    monkeypatch.setattr(swarm, "_ensure_valid_claims", fake_ensure_valid_claims)

    result = asyncio.run(swarm.execute_parallel({"rootdep": ["Write a spec"]}))

    assert result["status"] == "complete"
    assert len(calls) == 2  # initial run + retry
    assert calls[0][0] == "rootdep"
    assert calls[1][0] == "rootdep"
    assert "repair" in calls[1][1].lower() or "fix" in calls[1][1].lower()


def test_plan_mode_fails_when_spec_ready_still_invalid_after_retry(monkeypatch, tmp_path):
    """Plan mode: both RootDep runs produce invalid SPEC_READY — pipeline aborts."""
    project_id = "plan-fail-project"
    workspace = tmp_path / project_id
    workspace.mkdir()

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "plan"
    swarm.agents = {"rootdep": object()}

    calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append(agent_name)
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    async def fake_publish(*args, **kwargs):
        return True

    async def fake_ensure_valid_claims(claim_types, publish_if_missing=True):
        return "SPEC_READY is not valid: evidence missing"

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)
    monkeypatch.setattr(swarm, "_publish_agent_event", fake_publish)
    monkeypatch.setattr(swarm.blackboard, "publish_agent_event", fake_publish)
    monkeypatch.setattr(swarm, "_ensure_valid_claims", fake_ensure_valid_claims)

    result = asyncio.run(swarm.execute_parallel({"rootdep": ["Write a spec"]}))

    assert result["status"] == "error"
    assert "SPEC_READY" in result["error"]
    assert len(calls) == 2  # initial + one retry
