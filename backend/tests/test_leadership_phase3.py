import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claims import (
    ClaimStatus,
    ClaimType,
    FailureType,
    MAX_RECOVERY_RETRIES,
    build_claim_payload,
)
from src.swarm.claim_validators import (
    verify_claim_adversarially,
    _derive_evidence_for_claim_type,
    _compare_evidence,
)
from src.swarm.agents import AgentSwarm


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

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


def _make_claim(
    project_id="test-project",
    claim_type=ClaimType.BACKEND_API_READY,
    status=ClaimStatus.CLAIMED,
    claim_id="claim-1",
    producer_agent="backend",
    evidence_files=None,
    workspace_revision=None,
):
    return build_claim_payload(
        project_id=project_id,
        claim_type=claim_type,
        producer_agent=producer_agent,
        status=status,
        claim_id=claim_id,
        evidence={"files": evidence_files or ["backend/API_MANIFEST.json"]},
        workspace_revision=workspace_revision,
    )


# ---------------------------------------------------------------------------
# Adversarial Evidence Derivation
# ---------------------------------------------------------------------------

def test_derive_spec_evidence_finds_spec_md(tmp_project):
    workspace, _ = tmp_project
    (workspace / "SPEC.md").write_text("# Spec")
    result = _derive_evidence_for_claim_type(workspace, ClaimType.SPEC_READY.value)
    assert result["files"] == ["SPEC.md"]
    assert result["metadata"]["spec_exists"] is True


def test_derive_spec_evidence_empty_when_no_spec(tmp_project):
    workspace, _ = tmp_project
    result = _derive_evidence_for_claim_type(workspace, ClaimType.SPEC_READY.value)
    assert result["files"] == []


def test_derive_backend_runtime_finds_pom_and_app_yml(tmp_project):
    workspace, _ = tmp_project
    (workspace / "backend" / "pom.xml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "pom.xml").write_text("<project/>")
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").write_text("server:\n  port: 8080")
    (workspace / "backend" / "src" / "main" / "java" / "com" / "test" / "App.java").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "java" / "com" / "test" / "App.java").write_text("package com.test;")
    result = _derive_evidence_for_claim_type(workspace, ClaimType.BACKEND_RUNTIME_READY.value)
    assert "backend/pom.xml" in result["files"]
    assert "backend/src/main/resources/application.yml" in result["files"]
    assert result["metadata"]["java_source_count"] == 1


def test_derive_backend_api_finds_manifest_and_controllers(tmp_project):
    workspace, _ = tmp_project
    (workspace / "backend" / "API_MANIFEST.json").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "API_MANIFEST.json").write_text("{}")
    (workspace / "backend" / "src" / "main" / "java" / "UserController.java").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "java" / "UserController.java").write_text("class UserController {}")
    result = _derive_evidence_for_claim_type(workspace, ClaimType.BACKEND_API_READY.value)
    assert "backend/API_MANIFEST.json" in result["files"]
    assert result["metadata"]["controller_count"] == 1


def test_derive_deployment_finds_artifacts(tmp_project):
    workspace, _ = tmp_project
    (workspace / "docker-compose.yml").write_text("services:")
    (workspace / "backend" / "Dockerfile").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "Dockerfile").write_text("FROM openjdk:21")
    (workspace / "frontend" / "Dockerfile").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "frontend" / "Dockerfile").write_text("FROM node:20")
    result = _derive_evidence_for_claim_type(workspace, ClaimType.DEPLOYMENT_READY.value)
    assert "docker-compose.yml" in result["files"]
    assert "backend/Dockerfile" in result["files"]
    assert "frontend/Dockerfile" in result["files"]
    assert result["metadata"]["artifact_count"] == 3


# ---------------------------------------------------------------------------
# Evidence Comparison
# ---------------------------------------------------------------------------

def test_compare_evidence_passes_on_match():
    claimed = {"files": ["backend/pom.xml"], "metadata": {}}
    derived = {"files": ["backend/pom.xml"], "metadata": {}}
    result = _compare_evidence(claimed, derived)
    assert result["status"] == "valid"


def test_compare_evidence_fails_when_claim_missing_derived_files():
    claimed = {"files": ["backend/pom.xml"], "metadata": {}}
    derived = {"files": ["backend/pom.xml", "backend/src/main/resources/application.yml"], "metadata": {}}
    result = _compare_evidence(claimed, derived)
    assert result["status"] == "invalid"
    assert "Evidence mismatch" in result["errors"][0]
    assert "application.yml" in result["errors"][0]


def test_compare_evidence_warns_when_claim_has_extra_files():
    claimed = {"files": ["backend/pom.xml", "extra.txt"], "metadata": {}}
    derived = {"files": ["backend/pom.xml"], "metadata": {}}
    result = _compare_evidence(claimed, derived)
    assert result["status"] == "valid"  # extra files are warnings, not errors
    assert "extra.txt" in result["warnings"][0]


# ---------------------------------------------------------------------------
# Full Adversarial Verification
# ---------------------------------------------------------------------------

def test_adversarial_verifier_detects_missing_manifest(tmp_project):
    workspace, project_id = tmp_project
    # Workspace has controllers but NO manifest
    (workspace / "backend" / "src" / "main" / "java" / "UserController.java").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "java" / "UserController.java").write_text("class UserController {}")
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_API_READY,
        evidence_files=["backend/API_MANIFEST.json"],
    )
    result = verify_claim_adversarially(workspace, claim)
    # The agent claimed API_MANIFEST.json but it doesn't exist in the workspace.
    # The typed validator catches missing evidence files. Result is invalid
    # whether or not the adversarial comparison adds a duplicate warning.
    assert result["status"] == "invalid"
    assert any("Evidence file is missing: backend/API_MANIFEST.json" in e for e in result.get("errors", []))


def test_adversarial_verifier_detects_wrong_evidence_count(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "backend" / "pom.xml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "pom.xml").write_text("<project/>")
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").write_text("server: port: 8080")
    (workspace / "backend" / "src" / "main" / "java" / "App.java").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "java" / "App.java").write_text("class App {}")
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        evidence_files=["backend/pom.xml"],  # missing application.yml
    )
    result = verify_claim_adversarially(workspace, claim)
    assert result["status"] == "invalid"
    assert any("Evidence mismatch" in e for e in result.get("errors", []))


def test_adversarial_verifier_passes_on_matching_evidence(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "backend" / "pom.xml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "pom.xml").write_text(
        '<?xml version="1.0"?><project xmlns="http://maven.apache.org/POM/4.0.0">'
        '<parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>'
        '<version>3.2.0</version></parent><groupId>com.test</groupId><artifactId>test</artifactId>'
        '<version>1.0</version><properties><java.version>21</java.version></properties></project>'
    )
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "resources" / "application.yml").write_text("server:\n  port: 8080")
    (workspace / "backend" / "src" / "main" / "java" / "App.java").parent.mkdir(parents=True, exist_ok=True)
    (workspace / "backend" / "src" / "main" / "java" / "App.java").write_text("class App {}")
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        evidence_files=["backend/pom.xml", "backend/src/main/resources/application.yml"],
    )
    result = verify_claim_adversarially(workspace, claim)
    assert result["status"] == "valid"


def test_adversarial_verifier_flags_drift(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "SPEC.md").write_text("# Original Spec")
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.SPEC_READY,
        evidence_files=["SPEC.md"],
        status=ClaimStatus.VALID,
    )
    # Simulate drift: modify file after claim
    import time
    time.sleep(0.01)
    (workspace / "SPEC.md").write_text("# Modified Spec")
    result = verify_claim_adversarially(workspace, claim)
    assert result["status"] == "invalid"
    assert any("Evidence drift detected" in e for e in result.get("errors", []))


# ---------------------------------------------------------------------------
# Failure Classification
# ---------------------------------------------------------------------------

def test_classify_failure_detects_drift():
    swarm = AgentSwarm()
    ft = swarm._classify_failure("Evidence drift detected: SPEC.md was modified after claim")
    assert ft == FailureType.EVIDENCE_DRIFT


def test_classify_failure_detects_inconsistency():
    swarm = AgentSwarm()
    ft = swarm._classify_failure("Producer activity detected after claim (seq 3 -> 7)")
    assert ft == FailureType.AGENT_INCONSISTENT
    ft2 = swarm._classify_failure("backend is inconsistent")
    assert ft2 == FailureType.AGENT_INCONSISTENT


def test_classify_failure_detects_mismatch():
    swarm = AgentSwarm()
    ft = swarm._classify_failure("Evidence mismatch: agent did not claim files")
    assert ft == FailureType.EVIDENCE_MISMATCH


def test_classify_failure_detects_dependency_stale():
    swarm = AgentSwarm()
    ft = swarm._classify_failure("Dependency BACKEND_RUNTIME_READY is stale; expected valid")
    assert ft == FailureType.DEPENDENCY_STALE


def test_classify_failure_detects_compile_error():
    swarm = AgentSwarm()
    ft = swarm._classify_failure("Build verification failed for BACKEND_API_READY")
    assert ft == FailureType.COMPILE_ERROR
    ft2 = swarm._classify_failure("compilation error in UserController.java")
    assert ft2 == FailureType.COMPILE_ERROR


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quarantine_agent_sets_status_and_stales_claims(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        def __init__(self):
            self.claims = {}
            self.latest = {}
            self.published = []

        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            cid = self.latest.get(ct)
            return self.claims.get(cid) if cid else None

        async def update_claim_status(self, pid, cid, status, validation=None, reason=""):
            self.claims[cid]["status"] = status.value if hasattr(status, "value") else str(status)
            return self.claims[cid]

        async def publish_claim_event(self, pid, event_type, claim, data=None):
            self.published.append((event_type, claim, data))
            return {"type": event_type}

    store = FakeStore()
    claim = build_claim_payload(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_API_READY,
        producer_agent="backend",
        status=ClaimStatus.VALID,
        claim_id="api-1",
    )
    store.claims["api-1"] = claim
    store.latest[ClaimType.BACKEND_API_READY.value] = "api-1"
    swarm.claim_store_factory = lambda: store

    await swarm._quarantine_agent("backend", "Test quarantine reason")

    assert swarm._ensure_agent_state("backend")["status"] == "quarantined"
    assert store.claims["api-1"]["status"] == ClaimStatus.STALE.value
    assert any(e[0] == "claim_stale" for e in store.published)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_rollbacks_and_re_runs_agent(tmp_project):
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

    # Modify workspace after snapshot
    (workspace / "file.txt").write_text("v2")

    from src.swarm.claim_store import ClaimStore

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

    swarm.claim_store_factory = lambda: FakeStore()

    # Mock _run_single_agent to succeed
    async def fake_run(agent_name, task):
        return True

    swarm._run_single_agent = fake_run

    result = await swarm._recover_from_failure(
        ClaimType.BACKEND_RUNTIME_READY.value,
        FailureType.EVIDENCE_DRIFT,
        "Evidence drift detected",
    )

    assert result["status"] == "recovered"
    # Verify rollback happened
    assert (workspace / "file.txt").read_text() == "v1"


@pytest.mark.asyncio
async def test_recovery_fails_when_agent_re_run_fails(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            return None

    swarm.claim_store_factory = lambda: FakeStore()

    async def fake_run(agent_name, task):
        return False

    swarm._run_single_agent = fake_run

    result = await swarm._recover_from_failure(
        ClaimType.BACKEND_RUNTIME_READY.value,
        FailureType.EVIDENCE_DRIFT,
        "Evidence drift detected",
    )

    assert result["status"] == "error"
    assert "agent re-run failed" in result["error"]


@pytest.mark.asyncio
async def test_inconsistent_agent_triggers_quarantine_not_recovery(tmp_project):
    workspace, project_id = tmp_project
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            return None

    swarm.claim_store_factory = lambda: FakeStore()

    result = await swarm._recover_from_failure(
        ClaimType.BACKEND_RUNTIME_READY.value,
        FailureType.AGENT_INCONSISTENT,
        "Agent inconsistent after completion",
    )

    assert result["status"] == "error"
    assert "quarantined" in result["error"]
    assert swarm._ensure_agent_state("backend")["status"] == "quarantined"


# ---------------------------------------------------------------------------
# _ensure_valid_claim_with_recovery Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensure_valid_claim_with_recovery_succeeds_first_try(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "SPEC.md").write_text("# Spec")
    from src.swarm.tools.workspace_tools import set_project_context
    set_project_context(project_id)
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        def __init__(self):
            self.claims = {}

        async def close(self):
            pass

        async def get_claim(self, pid, cid):
            return build_claim_payload(
                project_id=pid,
                claim_type=ClaimType.SPEC_READY.value,
                producer_agent="rootdep",
                status=ClaimStatus.VALID,
                claim_id=cid,
                evidence={"files": ["SPEC.md"]},
            )

        async def get_latest_claim(self, pid, ct):
            return build_claim_payload(
                project_id=pid,
                claim_type=ct,
                producer_agent="rootdep",
                status=ClaimStatus.VALID,
                claim_id="spec-1",
                evidence={"files": ["SPEC.md"]},
            )

        async def update_claim_status(self, pid, cid, status, validation=None, reason=""):
            return {}

        async def publish_claim_event(self, pid, event_type, claim, data=None):
            return {"type": event_type}

        async def get_agent_event_seq(self, pid, agent):
            return 1

        async def save_agent_event_seq(self, pid, agent, seq):
            pass

    swarm.claim_store_factory = lambda: FakeStore()

    ok, error = await swarm._ensure_valid_claim_with_recovery(
        ClaimType.SPEC_READY.value, publish_if_missing=False
    )
    assert ok is True
    assert error == ""


@pytest.mark.asyncio
async def test_ensure_valid_claim_with_recovery_gives_up_after_max_retries(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "SPEC.md").write_text("# Spec")
    from src.swarm.tools.workspace_tools import set_project_context
    set_project_context(project_id)
    swarm = AgentSwarm()
    swarm.project_id = project_id
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        def __init__(self):
            self.claims = {}

        async def close(self):
            pass

        async def get_claim(self, pid, cid):
            return build_claim_payload(
                project_id=pid,
                claim_type=ClaimType.BACKEND_RUNTIME_READY.value,
                producer_agent="backend",
                status=ClaimStatus.VALID,
                claim_id=cid,
                evidence={"files": ["backend/missing.xml"]},
                workspace_revision="abc123",
            )

        async def get_latest_claim(self, pid, ct):
            # Always return a claim that will fail adversarial verification
            # because the evidence doesn't match workspace
            return build_claim_payload(
                project_id=pid,
                claim_type=ct,
                producer_agent="backend",
                status=ClaimStatus.VALID,
                claim_id="runtime-1",
                evidence={"files": ["backend/missing.xml"]},
                workspace_revision="abc123",
            )

        async def update_claim_status(self, pid, cid, status, validation=None, reason=""):
            return {}

        async def publish_claim_event(self, pid, event_type, claim, data=None):
            return {"type": event_type}

        async def get_agent_event_seq(self, pid, agent):
            return 1

        async def save_agent_event_seq(self, pid, agent, seq):
            pass

    swarm.claim_store_factory = lambda: FakeStore()

    # Mock _run_single_agent to succeed so recovery attempts happen
    async def fake_run(agent_name, task):
        return True

    swarm._run_single_agent = fake_run

    ok, error = await swarm._ensure_valid_claim_with_recovery(
        ClaimType.BACKEND_RUNTIME_READY.value, publish_if_missing=False
    )
    assert ok is False
    assert f"Max recovery retries ({MAX_RECOVERY_RETRIES}) exceeded" in error


@pytest.mark.asyncio
async def test_ensure_valid_claim_with_recovery_skips_for_missing_claim():
    swarm = AgentSwarm()
    swarm.project_id = "test"
    swarm.blackboard = AsyncMock()

    from src.swarm.claim_store import ClaimStore

    class FakeStore:
        async def close(self):
            pass

        async def get_latest_claim(self, pid, ct):
            return None

    swarm.claim_store_factory = lambda: FakeStore()

    ok, error = await swarm._ensure_valid_claim_with_recovery(
        ClaimType.BACKEND_RUNTIME_READY.value, publish_if_missing=False
    )
    assert ok is False
    assert "Missing required claim" in error
    # Should NOT have attempted recovery
    assert "Max recovery retries" not in error
