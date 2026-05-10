import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.swarm import agents as agents_module
from src.swarm.agents import AgentSwarm
from src.swarm.claims import ClaimType
from src.swarm.tools.coordination import _dependency_result
from src.swarm.tools import workspace_tools


def test_frontend_write_paths_are_scoped_to_frontend():
    workspace_tools.set_agent_workspace_scope("frontend")

    assert workspace_tools._scoped_write_path("package.json") == "frontend/package.json"
    assert workspace_tools._scoped_write_path("src/routes/+page.svelte") == "frontend/src/routes/+page.svelte"
    assert workspace_tools._scoped_write_path("frontend/package.json") == "frontend/package.json"


def test_backend_write_paths_are_scoped_to_backend():
    workspace_tools.set_agent_workspace_scope("backend")

    assert workspace_tools._scoped_write_path("pom.xml") == "backend/pom.xml"
    assert workspace_tools._scoped_write_path("src/main/resources/application.yml") == "backend/src/main/resources/application.yml"
    assert workspace_tools._scoped_write_path("backend/pom.xml") == "backend/pom.xml"


def test_backend_cannot_write_deployment_artifacts():
    workspace_tools.set_agent_workspace_scope("backend")

    assert "cannot write deployment artifact" in workspace_tools._deployment_write_violation("backend/Dockerfile")
    assert "cannot write deployment artifact" in workspace_tools._deployment_write_violation("backend/docker-compose.yml")


def test_frontend_cannot_write_deployment_artifacts():
    workspace_tools.set_agent_workspace_scope("frontend")

    assert "cannot write deployment artifact" in workspace_tools._deployment_write_violation("frontend/Dockerfile")
    assert "cannot write deployment artifact" in workspace_tools._deployment_write_violation("frontend/nginx.conf")


def test_workspace_writes_lock_after_terminal_completion():
    workspace_tools.set_agent_workspace_scope("backend")
    workspace_tools.lock_agent_workspace_writes()

    assert "cannot write after terminal completion" in workspace_tools._workspace_write_violation("backend/pom.xml")


def test_devops_write_paths_are_not_scoped():
    workspace_tools.set_agent_workspace_scope("devops")

    assert workspace_tools._scoped_write_path("docker-compose.yml") == "docker-compose.yml"
    assert workspace_tools._scoped_write_path("frontend/Dockerfile") == "frontend/Dockerfile"
    assert workspace_tools._deployment_write_violation("frontend/Dockerfile") is None


def test_dependency_result_preserves_backend_failure():
    result = _dependency_result("backend_api", {"status": "failed", "error": "backend failed"})

    assert result["status"] == "error"
    assert result["dependency"] == "backend_api"


def test_packager_barrier_rejects_incomplete_todos(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    swarm._set_agent_status("backend", "complete")
    swarm._set_agent_status("frontend", "complete")
    swarm._set_agent_status("devops", "complete")

    async def fake_get_agent_todos(project_id, agent_name):
        assert project_id == "project-1"
        if agent_name == "backend":
            return [
                {"content": "Write pom.xml", "status": "completed"},
                {"content": "Write controllers", "status": "in_progress"},
            ]
        return []

    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)

    error = asyncio.run(swarm._verify_packager_barrier(["backend", "frontend", "devops"], {"packager": []}))

    assert "backend reported completion with unfinished todos" in error
    assert "Write controllers" in error


def test_packager_barrier_accepts_completed_todos(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    for agent in ("backend", "frontend", "devops"):
        swarm._set_agent_status(agent, "complete")

    async def fake_get_agent_todos(project_id, agent_name):
        return [{"content": f"{agent_name} task", "status": "completed"}]

    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)

    assert asyncio.run(swarm._verify_packager_barrier(["backend", "frontend", "devops"], {"packager": []})) == ""


def test_packager_barrier_requires_devops_after_app_agents(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    for agent in ("backend", "frontend"):
        swarm._set_agent_status(agent, "complete")

    error = asyncio.run(swarm._verify_packager_barrier(["backend", "frontend"], {"packager": [], "devops": []}))

    assert "devops was selected but did not complete before packager" in error


def test_late_activity_after_completion_marks_agent_inconsistent(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    swarm._set_agent_status("backend", "complete")

    violation = asyncio.run(swarm._record_agent_activity("backend", "tool_start"))
    error = asyncio.run(swarm._verify_stage_barrier(["backend"]))

    assert "after terminal completion" in violation
    assert "after terminal completion" in error


def test_stage_barrier_rejects_non_terminal_agent(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    swarm._set_agent_status("frontend", "active")

    error = asyncio.run(swarm._verify_stage_barrier(["frontend"]))

    assert "frontend is not terminal" in error


def test_stabilization_window_detects_late_event(monkeypatch):
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)
    swarm = AgentSwarm()
    swarm.project_id = "project-1"
    swarm._set_agent_status("devops", "complete")
    swarm.agent_run_state["devops"]["terminal_at"] = datetime.now() - timedelta(seconds=10)
    asyncio.run(swarm._record_agent_activity("devops", "tool_call"))

    error = asyncio.run(swarm._verify_packager_barrier(["devops"], {"packager": []}))

    assert "after terminal completion" in error


class FakeClaimStore:
    """In-memory claim store for testing coordinator flow without Redis."""

    def __init__(self, claims=None):
        self.claims = dict(claims or {})  # claim_id -> claim
        self.latest = {}  # claim_type -> claim_id
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

    async def record_agent_violation(self, project_id, agent_name, violation_type, reason):
        pass

    async def get_agent_violation_count(self, project_id, agent_name, window_seconds):
        return 0


def _make_valid_claim(project_id, claim_type, producer_agent, claim_id, files=None):
    from src.swarm.claims import ClaimStatus, build_claim_payload
    return build_claim_payload(
        project_id=project_id,
        claim_type=claim_type,
        producer_agent=producer_agent,
        status=ClaimStatus.VALID,
        claim_id=claim_id,
        evidence={"files": files or []},
    )


def _setup_workspace_for_claims(workspace: Path):
    """Create minimal stub files so claim validation passes adversarial checks."""
    stubs = {
        "SPEC.md": "# Spec",
        "backend/pom.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<modelVersion>4.0.0</modelVersion>'
            '<parent><groupId>org.springframework.boot</groupId>'
            '<artifactId>spring-boot-starter-parent</artifactId><version>3.2.0</version></parent>'
            '<groupId>com.test</groupId><artifactId>test</artifactId><version>1.0</version>'
            '<properties><java.version>21</java.version></properties>'
            '</project>'
        ),
        "backend/src/main/resources/application.yml": "server:\n  port: 8080",
        "backend/src/main/java/com/test/App.java": "package com.test; public class App {}",
        "backend/API_MANIFEST.json": '{"endpoints":[]}',
        "frontend/package.json": (
            '{"name":"test","dependencies":{"@sveltejs/kit":"2","svelte":"5"},'
            '"scripts":{"build":"vite build","check":"svelte-check"}}'
        ),
        "frontend/src/app.html": "<html></html>",
        "docker-compose.yml": (
            "services:\n  backend:\n    build: ./backend\n  frontend:\n    build: ./frontend"
        ),
        "backend/Dockerfile": "FROM openjdk:21",
        "frontend/Dockerfile": "FROM node:20",
    }
    for rel_path, content in stubs.items():
        full = workspace / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)


def _setup_all_claims(fake_store, project_id, evidence_map=None):
    """Populate fake store with valid claims for all claim types.

    evidence_map: optional dict of claim_type -> evidence dict to override defaults.
    """
    from src.swarm.claims import ClaimStatus, build_claim_payload
    defaults = {
        ClaimType.SPEC_READY.value: {"files": ["SPEC.md"]},
        ClaimType.BACKEND_RUNTIME_READY.value: {"files": ["backend/pom.xml", "backend/src/main/resources/application.yml"]},
        ClaimType.BACKEND_API_READY.value: {"files": ["backend/API_MANIFEST.json"]},
        ClaimType.FRONTEND_SOURCE_READY.value: {"files": ["frontend/package.json", "frontend/src/app.html"]},
        ClaimType.FRONTEND_BUILD_READY.value: {"files": ["frontend/package.json"]},
        ClaimType.DEPLOYMENT_READY.value: {"files": ["docker-compose.yml", "backend/Dockerfile", "frontend/Dockerfile"]},
        ClaimType.PACKAGE_READY.value: {"files": []},
    }
    evidence_map = evidence_map or {}
    for ct in ClaimType:
        evidence = evidence_map.get(ct.value, defaults.get(ct.value, {"files": []}))
        claim = build_claim_payload(
            project_id=project_id,
            claim_type=ct.value,
            producer_agent="test",
            status=ClaimStatus.VALID,
            claim_id=f"claim-{ct.value}",
            evidence=evidence,
        )
        fake_store.claims[claim["id"]] = claim
        fake_store.latest[ct.value] = claim["id"]


def test_approved_build_skips_rootdep(monkeypatch, tmp_path):
    project_id = "approved-project"
    workspace = tmp_path / project_id
    workspace.mkdir()
    (workspace / "SPEC.md").write_text("# Approved Spec")

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "approved"
    swarm.agents = {"backend": object(), "frontend": object(), "devops": object(), "packager": object()}

    _setup_workspace_for_claims(workspace)
    fake_store = FakeClaimStore()
    _setup_all_claims(fake_store, project_id)
    swarm.claim_store_factory = lambda: fake_store

    calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append(agent_name)
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)

    result = asyncio.run(swarm.execute_parallel({
        "backend": ["backend task"],
        "frontend": ["frontend task"],
        "devops": ["devops task"],
        "packager": ["packager task"],
    }))

    assert result["status"] == "complete"
    assert calls == ["backend", "frontend", "devops", "packager"]
    assert "rootdep" not in calls


def test_approved_build_requires_existing_spec(monkeypatch, tmp_path):
    project_id = "missing-spec-project"
    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "approved"
    swarm.agents = {"backend": object()}

    async def fake_publish(*args, **kwargs):
        return True

    monkeypatch.setattr(swarm, "_publish_agent_event", fake_publish)

    result = asyncio.run(swarm.execute_parallel({"backend": ["backend task"]}))

    assert result["status"] == "error"
    assert "requires an existing SPEC.md" in result["error"]


def test_missing_backend_claim_blocks_devops(monkeypatch, tmp_path):
    project_id = "claim-block-project"
    workspace = tmp_path / project_id
    workspace.mkdir()
    (workspace / "SPEC.md").write_text("# Approved Spec")

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "approved"
    swarm.agents = {"backend": object(), "frontend": object(), "devops": object(), "packager": object()}
    calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append(agent_name)
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    _setup_workspace_for_claims(workspace)
    # Inject fake store with ALL claims EXCEPT BACKEND_RUNTIME_READY
    fake_store = FakeClaimStore()
    _setup_all_claims(fake_store, project_id)
    del fake_store.claims["claim-BACKEND_RUNTIME_READY"]
    del fake_store.latest["BACKEND_RUNTIME_READY"]
    swarm.claim_store_factory = lambda: fake_store

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)

    result = asyncio.run(swarm.execute_parallel({
        "backend": ["backend task"],
        "frontend": ["frontend task"],
        "devops": ["devops task"],
        "packager": ["packager task"],
    }))

    assert result["status"] == "error"
    assert "BACKEND_RUNTIME_READY" in result["error"]
    assert calls == ["backend"]


def test_missing_deployment_claim_blocks_packager(monkeypatch, tmp_path):
    project_id = "deployment-block-project"
    workspace = tmp_path / project_id
    workspace.mkdir()
    (workspace / "SPEC.md").write_text("# Approved Spec")

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.run_mode = "approved"
    swarm.agents = {"backend": object(), "frontend": object(), "devops": object(), "packager": object()}
    calls = []

    async def fake_run_single_agent(agent_name, task):
        calls.append(agent_name)
        swarm._set_agent_status(agent_name, "complete")
        return True

    async def fake_get_agent_todos(project_id_arg, agent_name):
        return []

    _setup_workspace_for_claims(workspace)
    # Inject fake store with ALL claims EXCEPT DEPLOYMENT_READY
    fake_store = FakeClaimStore()
    _setup_all_claims(fake_store, project_id)
    del fake_store.claims["claim-DEPLOYMENT_READY"]
    del fake_store.latest["DEPLOYMENT_READY"]
    swarm.claim_store_factory = lambda: fake_store

    monkeypatch.setattr(swarm, "_run_single_agent", fake_run_single_agent)
    monkeypatch.setattr("src.swarm.agents.get_agent_todos", fake_get_agent_todos)

    result = asyncio.run(swarm.execute_parallel({
        "backend": ["backend task"],
        "frontend": ["frontend task"],
        "devops": ["devops task"],
        "packager": ["packager task"],
    }))

    # Missing DEPLOYMENT_READY is now a warning, not a hard error — packager
    # still runs so the user gets a usable artifact even when devops fails.
    assert result["status"] == "complete"
    assert "packager" in calls


# ---------------------------------------------------------------------------
# Phase 7: Claim Revocation and Staleness — coordinator integration
# ---------------------------------------------------------------------------

def test_auto_finalize_todos_matches_work_log(monkeypatch, tmp_path):
    """_auto_finalize_todos only marks todos whose work was actually performed."""
    import os
    import redis.asyncio as redis
    from src.swarm.agents import WorkLog
    project_id = "finalize-project"

    monkeypatch.setattr("src.swarm.tools.workspace_tools.WORKSPACE_BASE", tmp_path)

    swarm = AgentSwarm()
    swarm.project_id = project_id

    async def _seed_and_verify():
        # Seed initial todos in Redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        try:
            key = f"project:{project_id}:agent:backend:todos"
            await r.set(key, json.dumps([
                {"content": "Write pom.xml", "status": "completed"},
                {"content": "Write entities", "status": "in_progress"},
                {"content": "Write controllers", "status": "pending"},
                {"content": "Research best practices", "status": "pending"},
            ]), ex=3600)
        finally:
            await r.aclose()

        # Simulate work log: wrote entities, did a search, but NOT controllers
        work_log = WorkLog()
        work_log.record_tool("write_file", {"file_path": "backend/src/main/java/com/productflow/entity/Product.java"})
        work_log.record_tool("web_search", {})

        await swarm._auto_finalize_todos("backend", work_log)

        # Verify: entities and research marked done; controllers left pending
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        try:
            raw = await r.get(key)
            todos = json.loads(raw)
            by_content = {t["content"]: t["status"] for t in todos}
            assert by_content["Write pom.xml"] == "completed"
            assert by_content["Write entities"] == "completed"  # matched write_file
            assert by_content["Research best practices"] == "completed"  # matched web_search
            assert by_content["Write controllers"] == "pending"  # no matching work
        finally:
            await r.aclose()

    asyncio.run(_seed_and_verify())


def test_inconsistent_agent_auto_stales_its_claims(monkeypatch, tmp_path):
    """Task 7.1: Post-completion activity marks agent inconsistent and stales claims."""
    project_id = "inconsistent-project"
    monkeypatch.setattr(agents_module, "PACKAGER_STABILIZATION_SECONDS", 0)

    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm._set_agent_status("backend", "complete")

    # Setup a valid claim in a fake store
    from src.swarm.claims import ClaimType, ClaimStatus, build_claim_payload
    claim = build_claim_payload(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_API_READY.value,
        producer_agent="backend",
        status=ClaimStatus.VALID,
        claim_id="api-1",
        now="2026-05-07T00:00:00Z",
    )

    class FakeStore:
        def __init__(self):
            self.claims = {"api-1": claim}
            self.published = []
        async def connect(self): pass
        async def close(self): pass
        async def get_latest_claim(self, pid, ct):
            for c in self.claims.values():
                if c["claim_type"] == ct:
                    return c
            return None
        async def get_claim(self, pid, cid):
            return self.claims[cid]
        async def update_claim_status(self, pid, cid, status, reason=""):
            self.claims[cid]["status"] = status.value if hasattr(status, "value") else str(status)
            self.claims[cid].setdefault("validation", {})
            self.claims[cid]["validation"].setdefault("errors", [])
            if reason:
                self.claims[cid]["validation"]["errors"].append(reason)
            return self.claims[cid]
        async def publish_claim_event(self, pid, event_type, claim, data=None):
            self.published.append((event_type, claim["id"]))
            return {}
        async def record_agent_violation(self, pid, agent_name, violation_type, reason):
            pass
        async def get_agent_violation_count(self, pid, agent_name, window_seconds):
            return 0

    fake_store = FakeStore()
    swarm.claim_store_factory = lambda: fake_store

    # Emit post-completion activity → should mark agent inconsistent and stale claims
    violation = asyncio.run(swarm._record_agent_activity("backend", "tool_start"))
    assert "after terminal completion" in violation

    # Give the background _stale_agent_claims coroutine a chance to run
    async def drain():
        pass
    asyncio.run(drain())

    # The claim should now be stale
    assert fake_store.claims["api-1"]["status"] == ClaimStatus.STALE.value
    assert "after terminal completion" in fake_store.claims["api-1"]["validation"]["errors"][0]
    assert any(evt[0] == "claim_stale" for evt in fake_store.published)



