import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claims import ClaimStatus, ClaimType, build_claim_payload
from src.swarm.claim_store import ClaimStore
from src.swarm.tools.workspace_tools import (
    snapshot_workspace,
    rollback_workspace,
    WORKSPACE_BASE,
    set_project_context,
    set_agent_workspace_scope,
    _check_claimed_evidence,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}
        self.zsets: dict[str, list[tuple[float, str]]] = {}
        self.published = []

    async def ping(self):
        return True

    async def aclose(self):
        return None

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


def _make_store():
    return ClaimStore(redis_client=FakeRedis(), ttl_seconds=100)


def _make_claim(
    project_id="project-1",
    claim_type=ClaimType.BACKEND_API_READY,
    status=ClaimStatus.CLAIMED,
    claim_id="claim-1",
    producer_agent="backend",
    evidence_files=None,
):
    return build_claim_payload(
        project_id=project_id,
        claim_type=claim_type,
        producer_agent=producer_agent,
        evidence={"files": evidence_files or ["backend/API_MANIFEST.json"]},
        status=status,
        claim_id=claim_id,
    )


# ---------------------------------------------------------------------------
# Git Snapshot Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project workspace."""
    project_id = "test-project"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)
    # Monkey-patch WORKSPACE_BASE for the test
    import src.swarm.tools.workspace_tools as wtools
    orig_base = wtools.WORKSPACE_BASE
    wtools.WORKSPACE_BASE = tmp_path
    yield workspace, project_id
    wtools.WORKSPACE_BASE = orig_base


def test_snapshot_creates_git_commit(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "hello.txt").write_text("hello")

    git_hash = snapshot_workspace(project_id, "test-label")

    assert git_hash is not None
    assert len(git_hash) == 40  # SHA-1 hash length
    git_dir = workspace / ".git"
    assert git_dir.exists()


def test_rollback_restores_workspace(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "file.txt").write_text("version1")

    git_hash = snapshot_workspace(project_id, "v1")
    assert git_hash is not None

    # Modify after snapshot
    (workspace / "file.txt").write_text("version2")
    (workspace / "new.txt").write_text("i am new")

    # Rollback
    result = rollback_workspace(project_id, git_hash)
    assert result is True

    assert (workspace / "file.txt").read_text() == "version1"
    assert not (workspace / "new.txt").exists()


def test_snapshot_returns_none_when_git_unavailable(tmp_path, monkeypatch):
    """If git binary is missing, snapshot should return None gracefully."""
    monkeypatch.setenv("PATH", "/nonexistent")
    workspace = tmp_path / "no-git-project"
    workspace.mkdir()

    import src.swarm.tools.workspace_tools as wtools
    orig_base = wtools.WORKSPACE_BASE
    wtools.WORKSPACE_BASE = tmp_path

    try:
        git_hash = snapshot_workspace("no-git-project", "test")
        assert git_hash is None
    finally:
        wtools.WORKSPACE_BASE = orig_base


# ---------------------------------------------------------------------------
# Pre-Write Guardrail Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_blocked_by_valid_claim(tmp_project):
    workspace, project_id = tmp_project
    store = _make_store()

    # Create a valid claim that locks backend/pom.xml
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.VALID,
        claim_id="runtime-1",
        producer_agent="backend",
        evidence_files=["backend/pom.xml"],
    )
    await store.save_claim(project_id, claim)

    set_project_context(project_id)
    set_agent_workspace_scope("backend")

    with patch("src.swarm.claim_store.ClaimStore", return_value=store):
        violation = await _check_claimed_evidence("backend/pom.xml")
    assert violation is not None
    assert "cannot modify" in violation
    assert "BACKEND_RUNTIME_READY" in violation


@pytest.mark.asyncio
async def test_write_allowed_after_claim_stale(tmp_project):
    workspace, project_id = tmp_project
    store = _make_store()

    # Create a STALE claim that references backend/pom.xml
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.STALE,
        claim_id="runtime-stale",
        producer_agent="backend",
        evidence_files=["backend/pom.xml"],
    )
    await store.save_claim(project_id, claim)

    set_project_context(project_id)
    set_agent_workspace_scope("backend")

    with patch("src.swarm.claim_store.ClaimStore", return_value=store):
        violation = await _check_claimed_evidence("backend/pom.xml")
    assert violation is None  # Stale claims don't lock files


@pytest.mark.asyncio
async def test_write_allowed_for_unclaimed_file(tmp_project):
    workspace, project_id = tmp_project
    store = _make_store()

    # Valid claim for API_MANIFEST.json
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_API_READY,
        status=ClaimStatus.VALID,
        claim_id="api-1",
        producer_agent="backend",
        evidence_files=["backend/API_MANIFEST.json"],
    )
    await store.save_claim(project_id, claim)

    set_project_context(project_id)
    set_agent_workspace_scope("backend")

    # Writing a DIFFERENT file should be allowed
    with patch("src.swarm.claim_store.ClaimStore", return_value=store):
        violation = await _check_claimed_evidence("backend/pom.xml")
    assert violation is None


@pytest.mark.asyncio
async def test_write_allowed_for_different_agent(tmp_project):
    workspace, project_id = tmp_project
    store = _make_store()

    # Backend has a valid claim
    claim = _make_claim(
        project_id=project_id,
        claim_type=ClaimType.BACKEND_API_READY,
        status=ClaimStatus.VALID,
        claim_id="api-1",
        producer_agent="backend",
        evidence_files=["backend/API_MANIFEST.json"],
    )
    await store.save_claim(project_id, claim)

    set_project_context(project_id)
    set_agent_workspace_scope("frontend")  # Different agent

    # Frontend should be allowed to write backend files (not its scope anyway,
    # but the guardrail specifically checks the agent name)
    with patch("src.swarm.claim_store.ClaimStore", return_value=store):
        violation = await _check_claimed_evidence("backend/API_MANIFEST.json")
    assert violation is None


# ---------------------------------------------------------------------------
# Claim Evidence Enrichment Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_includes_git_hash(tmp_project):
    workspace, project_id = tmp_project
    (workspace / "SPEC.md").write_text("# Spec")

    # Snapshot first to get a git repo
    git_hash = snapshot_workspace(project_id, "SPEC_READY")
    assert git_hash is not None

    from src.swarm.tools.claim_tools import publish_claim_record

    store = _make_store()
    result = await publish_claim_record(
        project_id=project_id,
        producer_agent="rootdep",
        claim_type=ClaimType.SPEC_READY.value,
        evidence={"files": ["SPEC.md"]},
        store=store,
    )

    claim = result["claim"]
    # The claim should have workspace_revision set to a git hash
    assert claim.get("workspace_revision") is not None
    assert len(claim["workspace_revision"]) == 40
    # Evidence metadata should also include it
    evidence = claim.get("evidence", {})
    metadata = evidence.get("metadata", {})
    assert metadata.get("workspace_revision") == claim["workspace_revision"]
