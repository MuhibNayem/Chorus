import asyncio
from pathlib import Path

from src.blackboard.redis_blackboard import RedisBlackboard
from src.main import start_plan_swarm_background
from src.swarm.agents import AgentSwarm
from src.swarm.claims import ClaimStatus, ClaimType, build_claim_payload
from src.swarm.tools.workspace_tools import set_project_context


class FakeBlackboard:
    def __init__(self):
        self.events = []
        self.project_states = []
        self._redis = object()

    async def connect(self):
        pass

    async def publish_agent_event(self, project_id, agent_name, event_type, content, data=None):
        self.events.append(
            {
                "project_id": project_id,
                "agent_name": agent_name,
                "event_type": event_type,
                "content": content,
                "data": data or {},
            }
        )

    async def set_project_state(self, project_id, state):
        self.project_states.append({"project_id": project_id, "state": state})


class FakeDatabase:
    def __init__(self):
        self.status_updates = []
        self.spec_updates = []
        self.messages = []
        self.projects = {}
        self._pool = object()

    async def connect(self):
        pass

    async def init_schema(self):
        pass

    async def ensure_project(self, project_id, name, spec, status):
        self.projects[project_id] = {"id": project_id, "name": name, "spec": spec, "status": status}

    async def update_project_status(self, project_id, status):
        self.status_updates.append((project_id, status))
        self.projects.setdefault(project_id, {"id": project_id, "spec": {}})
        self.projects[project_id]["status"] = status

    async def update_project_spec(self, project_id, spec, status=None):
        self.spec_updates.append((project_id, spec, status))
        self.projects.setdefault(project_id, {"id": project_id})
        self.projects[project_id]["spec"] = spec
        if status is not None:
            self.projects[project_id]["status"] = status

    async def save_chat_message(self, **kwargs):
        self.messages.append(kwargs)

    async def get_project(self, project_id):
        return self.projects.get(project_id)


class FakeClaimStore:
    def __init__(self, claim):
        self.claim = claim
        self.saved_claims = [claim]

    async def close(self):
        pass

    async def get_latest_claim(self, project_id, claim_type):
        if self.claim and self.claim["claim_type"] == claim_type:
            return self.claim
        return None

    async def get_claim(self, project_id, claim_id):
        if self.claim and self.claim["id"] == claim_id:
            return self.claim
        raise KeyError(claim_id)

    async def update_claim_status(self, project_id, claim_id, status, validation=None, reason=""):
        if self.claim and self.claim["id"] == claim_id:
            self.claim["status"] = status.value if hasattr(status, "value") else str(status)
            if validation is not None:
                self.claim["validation"] = validation
            return self.claim
        raise KeyError(claim_id)

    async def publish_claim_event(self, project_id, event_type, claim, data=None):
        return {"type": event_type, "claim_id": claim["id"]}

    async def get_agent_event_seq(self, project_id, agent_name):
        return None

    async def save_claim(self, project_id, claim):
        self.claim = claim
        self.saved_claims.append(claim)
        return claim


def test_plan_background_does_not_publish_plan_ready_when_execution_fails(monkeypatch, tmp_path):
    import src.main as main_module

    project_id = "plan-runtime-fail"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)

    fake_blackboard = FakeBlackboard()
    fake_database = FakeDatabase()

    monkeypatch.setattr(main_module, "WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(main_module, "blackboard", fake_blackboard)
    monkeypatch.setattr(main_module, "database", fake_database)

    async def fake_warmup(project_id_arg):
        return None

    monkeypatch.setattr(main_module, "ensure_workspace_is_warm", fake_warmup)

    async def fake_initialize(self, project_id_arg, project_spec):
        self.project_id = project_id_arg
        self.run_mode = "plan"

    async def fake_execute_parallel(self, task_definitions):
        return {"status": "error", "error": "SPEC_READY barrier failed"}

    async def fake_shutdown(self):
        return None

    monkeypatch.setattr(AgentSwarm, "initialize", fake_initialize)
    monkeypatch.setattr(AgentSwarm, "execute_parallel", fake_execute_parallel)
    monkeypatch.setattr(AgentSwarm, "shutdown", fake_shutdown)

    asyncio.run(start_plan_swarm_background(project_id, "Build something", "auto"))

    event_types = [event["event_type"] for event in fake_blackboard.events]
    assert "plan_ready" not in event_types
    assert "complete" not in event_types
    assert "error" in event_types
    assert fake_database.projects[project_id]["status"] == "error"


def test_spec_ready_invalid_claim_is_republished_from_workspace(monkeypatch, tmp_path):
    project_id = "spec-republish-project"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)
    (workspace / "SPEC.md").write_text("# Spec")

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr("src.swarm.agents.WORKSPACE_BASE", tmp_path, raising=False)

    bad_claim = build_claim_payload(
        project_id=project_id,
        claim_type=ClaimType.SPEC_READY,
        producer_agent="rootdep",
        evidence={"files": []},
        status=ClaimStatus.CLAIMED,
        claim_id="claim-bad-spec",
    )
    store = FakeClaimStore(bad_claim)

    swarm = AgentSwarm(blackboard=RedisBlackboard())
    swarm.project_id = project_id
    swarm.claim_store_factory = lambda: store
    set_project_context(project_id)

    ok, error = asyncio.run(swarm._ensure_valid_claim(ClaimType.SPEC_READY.value))

    assert ok is True
    assert error == ""
    assert store.claim["evidence"]["files"] == ["SPEC.md"]
    assert store.claim["id"] != "claim-bad-spec"
