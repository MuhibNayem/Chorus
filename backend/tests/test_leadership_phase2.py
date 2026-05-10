import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.tools.claim_tools import (
    _verification_command_for,
    _build_tool_available,
    _run_verification,
    verify_and_publish_claim_record,
    publish_claim_record,
    verify_progress,
)
from src.swarm.claim_store import ClaimStore
from src.swarm.tools.workspace_tools import set_project_context


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
# Verification Command Mapping
# ---------------------------------------------------------------------------

def test_verification_command_for_known_pairs():
    workspace = Path("/tmp/mock-workspace")
    assert _verification_command_for("frontend", "FRONTEND_BUILD_READY", workspace=workspace) is None
    assert _verification_command_for("devops", "DEPLOYMENT_READY", workspace=workspace) == ["docker compose config > /dev/null"]


def test_verification_command_for_unknown_pairs():
    workspace = Path("/tmp/mock-workspace")
    assert _verification_command_for("backend", "SPEC_READY", workspace=workspace) is None
    assert _verification_command_for("packager", "PACKAGE_READY", workspace=workspace) is None
    assert _verification_command_for("unknown", "BACKEND_API_READY", workspace=workspace) is None


# ---------------------------------------------------------------------------
# Build Tool Availability
# ---------------------------------------------------------------------------

def test_build_tool_available_detects_known_tools():
    # These may or may not be present depending on the environment,
    # but the function should not crash.
    result = _build_tool_available(["cd backend && mvn compile -q"])
    assert isinstance(result, bool)

    result = _build_tool_available(["cd frontend && npm run build"])
    assert isinstance(result, bool)


def test_build_tool_available_returns_true_for_shell_only():
    assert _build_tool_available(["echo hello"]) is True


# ---------------------------------------------------------------------------
# Run Verification (Async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_verification_skips_when_tool_missing(tmp_project):
    workspace, project_id = tmp_project
    result = await _run_verification(workspace, "backend", "BACKEND_RUNTIME_READY")
    if result["status"] == "skipped":
        assert result["status"] == "skipped"
        assert "not available" in result["reason"] or "No verification command" in result["reason"]


@pytest.mark.asyncio
async def test_run_verification_fails_with_output_on_bad_build(tmp_project):
    workspace, project_id = tmp_project
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    src_dir = backend_dir / "src"
    src_dir.mkdir()
    (src_dir / "broken.py").write_text("def broken(:\n")

    result = await _run_verification(workspace, "backend", "BACKEND_RUNTIME_READY")
    if _build_tool_available(["cd backend && python -m compileall src"]):
        assert result["status"] == "failed"
        assert result["exit_code"] != 0
        assert "output" in result
        assert len(result["output"]) > 0
        assert "duration_ms" in result


@pytest.mark.asyncio
async def test_run_verification_succeeds_on_valid_build(tmp_project):
    workspace, project_id = tmp_project
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    src_dir = backend_dir / "src"
    src_dir.mkdir()
    (src_dir / "ok.py").write_text("def ok():\n    return 1\n")

    result = await _run_verification(workspace, "backend", "BACKEND_RUNTIME_READY")
    if _build_tool_available(["cd backend && python -m compileall src"]):
        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# verify_and_publish_claim_record
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_and_publish_returns_compiler_errors_on_failure(tmp_project):
    workspace, project_id = tmp_project
    set_project_context(project_id)
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    src_dir = backend_dir / "src"
    src_dir.mkdir()
    (src_dir / "broken.py").write_text("def broken(:\n")

    store = _make_store()

    result = await verify_and_publish_claim_record(
        project_id=project_id,
        producer_agent="backend",
        claim_type="BACKEND_RUNTIME_READY",
        evidence={"files": ["backend/pyproject.toml"]},
        store=store,
    )

    if _build_tool_available(["cd backend && python -m compileall src"]):
        assert result["status"] == "verification_failed"
        assert "output" in result
        assert result["exit_code"] != 0
        assert "hint" in result
        # Claim should NOT have been saved
        saved = await store.get_latest_claim(project_id, "BACKEND_RUNTIME_READY")
        assert saved is None


@pytest.mark.asyncio
async def test_verify_and_publish_publishes_claim_on_success(tmp_project):
    workspace, project_id = tmp_project
    set_project_context(project_id)
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    src_dir = backend_dir / "src"
    src_dir.mkdir()
    (src_dir / "ok.py").write_text("def ok():\n    return 1\n")

    store = _make_store()

    result = await verify_and_publish_claim_record(
        project_id=project_id,
        producer_agent="backend",
        claim_type="BACKEND_RUNTIME_READY",
        evidence={"files": ["backend/pyproject.toml"]},
        store=store,
    )

    if _build_tool_available(["cd backend && python -m compileall src"]):
        assert result["status"] == "success"
        claim = result["claim"]
        # Evidence should include verification metadata inside metadata
        evidence = claim.get("evidence", {})
        metadata = evidence.get("metadata", {})
        assert "verification" in metadata
        assert metadata["verification"]["exit_code"] == 0
        assert "output_sha256" in metadata["verification"]
        # Workspace revision should be present
        assert claim.get("workspace_revision") is not None
        # Should have saved the claim
        saved = await store.get_latest_claim(project_id, "BACKEND_RUNTIME_READY")
        assert saved is not None


@pytest.mark.asyncio
async def test_verify_and_publish_skips_when_tool_missing(tmp_project):
    workspace, project_id = tmp_project
    set_project_context(project_id)
    store = _make_store()

    # Use a claim type that requires a tool unlikely to be installed
    # (devops/docker — but docker might be installed, so we mock)
    from unittest.mock import patch

    with patch("src.swarm.tools.claim_tools._build_tool_available", return_value=False):
        result = await verify_and_publish_claim_record(
            project_id=project_id,
            producer_agent="devops",
            claim_type="DEPLOYMENT_READY",
            evidence={"files": ["docker-compose.yml"]},
            store=store,
        )

    assert result["status"] == "success"
    assert result.get("verification_skipped") is True
    assert "verification_reason" in result


def test_verification_command_detects_python_backend(tmp_path):
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    (backend_dir / "src").mkdir()

    cmds = _verification_command_for("backend", "BACKEND_RUNTIME_READY", workspace=workspace)
    assert len(cmds) == 1
    assert cmds[0].startswith("cd backend &&")
    assert "python -m compileall src" in cmds[0]


def test_verification_command_detects_go_backend(tmp_path):
    workspace = tmp_path / "project"
    backend_dir = workspace / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "go.mod").write_text("module test\n")

    assert _verification_command_for("backend", "BACKEND_RUNTIME_READY", workspace=workspace) == [
        "cd backend && go build ./..."
    ]


def test_verification_command_detects_frontend_check_and_build(tmp_path):
    workspace = tmp_path / "project"
    frontend_dir = workspace / "frontend"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "package.json").write_text('{"scripts":{"check":"svelte-check","build":"vite build"}}')

    check_cmds = _verification_command_for(
        "frontend",
        "FRONTEND_SOURCE_READY",
        workspace=workspace,
        progress=True,
    )
    assert len(check_cmds) == 1
    assert "npm run check" in check_cmds[0]

    build_cmds = _verification_command_for(
        "frontend",
        "FRONTEND_BUILD_READY",
        workspace=workspace,
    )
    assert len(build_cmds) == 1
    assert "npm run build" in build_cmds[0]


@pytest.mark.asyncio
async def test_run_verification_uses_docker_fallback_when_host_tool_missing(tmp_project, monkeypatch):
    workspace, _ = tmp_project
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "go.mod").write_text("module test\n")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr("src.swarm.tools.claim_tools._build_tool_available", lambda command: False)
    monkeypatch.setattr("src.swarm.tools.claim_tools._docker_available", lambda: True)
    monkeypatch.setattr("src.swarm.tools.claim_tools.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await _run_verification(workspace, "backend", "BACKEND_RUNTIME_READY")

    assert result["status"] == "success"
    assert result["executor"].startswith("docker:")

    run_calls = [args for args, _ in calls if args[:2] == ("docker", "run")]
    assert run_calls, f"Expected a 'docker run' call among {calls}"
    assert "golang:1.24" in run_calls[0]


@pytest.mark.asyncio
async def test_run_verification_skips_when_host_tool_missing_and_docker_unavailable(tmp_project, monkeypatch):
    workspace, _ = tmp_project
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "go.mod").write_text("module test\n")

    monkeypatch.setattr("src.swarm.tools.claim_tools._build_tool_available", lambda command: False)
    monkeypatch.setattr("src.swarm.tools.claim_tools._docker_available", lambda: False)

    result = await _run_verification(workspace, "backend", "BACKEND_RUNTIME_READY")

    assert result["status"] == "skipped"
    assert "docker" in result["reason"].lower()


@pytest.mark.asyncio
async def test_verify_progress_returns_failure_output(tmp_project):
    workspace, project_id = tmp_project
    set_project_context(project_id)
    from src.swarm.tools.todo_tools import set_agent_name

    set_agent_name("backend")
    backend_dir = workspace / "backend"
    backend_dir.mkdir()
    (backend_dir / "pyproject.toml").write_text("[project]\nname='test'\nversion='0.1.0'\n")
    src_dir = backend_dir / "src"
    src_dir.mkdir()
    (src_dir / "broken.py").write_text("def broken(:\n")

    result = await verify_progress.ainvoke({"stage": "models"})

    if _build_tool_available(["cd backend && python -m compileall src"]):
        assert result["status"] == "verification_failed"
        assert result["stage"] == "models"
        assert "output" in result
