import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claim_store import ClaimStore
from src.swarm.claims import ClaimStatus, ClaimType, build_claim_payload
from src.swarm.tools.claim_tools import (
    publish_claim_record,
    revoke_claim,
    validate_claim,
    validate_dependencies,
    wait_for_claim_record,
    _cascade_staleness,
    _run_verification,
    verify_and_publish_claim_record,
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


def make_store():
    return ClaimStore(redis_client=FakeRedis(), ttl_seconds=100)


def make_claim(
    claim_type=ClaimType.BACKEND_API_READY,
    status=ClaimStatus.CLAIMED,
    depends_on=None,
    claim_id="claim-1",
    producer_event_seq=None,
    producer_agent="backend",
    now=None,
):
    return build_claim_payload(
        project_id="project-1",
        claim_type=claim_type,
        producer_agent=producer_agent,
        evidence={"files": ["backend/API_MANIFEST.json"]},
        depends_on=depends_on,
        status=status,
        claim_id=claim_id,
        producer_event_seq=producer_event_seq,
        now=now,
    )


@pytest.mark.asyncio
async def test_publish_claim_record_builds_and_persists_claim():
    store = make_store()

    result = await publish_claim_record(
        project_id="project-1",
        producer_agent="backend",
        claim_type=ClaimType.BACKEND_API_READY.value,
        evidence={"files": ["backend/API_MANIFEST.json"]},
        depends_on=[ClaimType.BACKEND_RUNTIME_READY.value],
        store=store,
    )

    assert result["status"] == "success"
    claim = result["claim"]
    assert claim["project_id"] == "project-1"
    assert claim["producer_agent"] == "backend"
    assert claim["claim_type"] == ClaimType.BACKEND_API_READY.value
    assert claim["status"] == ClaimStatus.CLAIMED.value
    assert claim["evidence"]["files"] == ["backend/API_MANIFEST.json"]
    assert claim["depends_on"] == [ClaimType.BACKEND_RUNTIME_READY.value]
    assert await store.get_latest_claim("project-1", ClaimType.BACKEND_API_READY.value) == claim


@pytest.mark.asyncio
async def test_publish_claim_record_expands_glob_evidence(tmp_path):
    import src.swarm.tools.workspace_tools as wtools

    project_id = "project-1"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)
    models_dir = workspace / "backend" / "internal" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "user.go").write_text("package models")

    orig_base = wtools.WORKSPACE_BASE
    wtools.WORKSPACE_BASE = tmp_path
    try:
        store = make_store()
        result = await publish_claim_record(
            project_id=project_id,
            producer_agent="backend",
            claim_type=ClaimType.BACKEND_RUNTIME_READY.value,
            evidence={"files": ["backend/internal/models/*.go"]},
            store=store,
        )
    finally:
        wtools.WORKSPACE_BASE = orig_base

    assert result["status"] == "success"
    assert result["claim"]["evidence"]["files"] == ["backend/internal/models/user.go"]


@pytest.mark.asyncio
async def test_wait_for_claim_record_returns_only_valid_claim():
    store = make_store()
    valid_claim = make_claim(status=ClaimStatus.VALID)
    await store.save_claim("project-1", valid_claim)

    result = await wait_for_claim_record(
        project_id="project-1",
        claim_type=ClaimType.BACKEND_API_READY.value,
        timeout_seconds=0,
        store=store,
    )

    assert result == {"status": "success", "claim": valid_claim}


@pytest.mark.asyncio
async def test_wait_for_claim_record_rejects_invalid_dependency_claim():
    store = make_store()
    invalid_claim = make_claim(status=ClaimStatus.INVALID)
    await store.save_claim("project-1", invalid_claim)

    result = await wait_for_claim_record(
        project_id="project-1",
        claim_type=ClaimType.BACKEND_API_READY.value,
        timeout_seconds=0,
        store=store,
    )

    assert result["status"] == "error"
    assert "is invalid" in result["error"]
    assert result["claim"] == invalid_claim


@pytest.mark.asyncio
async def test_wait_for_claim_record_times_out_when_claim_not_valid():
    store = make_store()
    await store.save_claim("project-1", make_claim(status=ClaimStatus.CLAIMED))

    result = await wait_for_claim_record(
        project_id="project-1",
        claim_type=ClaimType.BACKEND_API_READY.value,
        timeout_seconds=0,
        store=store,
    )

    assert result["status"] == "error"
    assert "Timed out" in result["error"]


@pytest.mark.asyncio
async def test_validate_dependencies_blocks_missing_dependency():
    store = make_store()
    claim = make_claim(depends_on=[ClaimType.BACKEND_RUNTIME_READY.value])

    result = await validate_dependencies("project-1", claim, store=store)

    assert result["status"] == "invalid"
    assert result["dependencies"] == [{
        "claim_type": ClaimType.BACKEND_RUNTIME_READY.value,
        "status": "missing",
        "claim_id": None,
    }]
    assert "Missing dependency claim" in result["errors"][0]


@pytest.mark.asyncio
async def test_validate_dependencies_blocks_invalid_dependency():
    store = make_store()
    dependency = make_claim(
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.STALE,
        claim_id="dependency-1",
    )
    await store.save_claim("project-1", dependency)
    claim = make_claim(depends_on=[ClaimType.BACKEND_RUNTIME_READY.value])

    result = await validate_dependencies("project-1", claim, store=store)

    assert result["status"] == "invalid"
    assert result["dependencies"] == [{
        "claim_type": ClaimType.BACKEND_RUNTIME_READY.value,
        "status": ClaimStatus.STALE.value,
        "claim_id": "dependency-1",
    }]
    assert "expected valid" in result["errors"][0]


@pytest.mark.asyncio
async def test_validate_dependencies_accepts_valid_dependency():
    store = make_store()
    dependency = make_claim(
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.VALID,
        claim_id="dependency-1",
    )
    await store.save_claim("project-1", dependency)
    claim = make_claim(depends_on=[ClaimType.BACKEND_RUNTIME_READY.value])

    result = await validate_dependencies("project-1", claim, store=store)

    assert result["status"] == "valid"
    assert result["errors"] == []
    assert result["dependencies"][0]["claim_id"] == "dependency-1"


@pytest.mark.asyncio
async def test_validate_claim_updates_status_and_publishes_event(tmp_path):
    store = make_store()
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "API_MANIFEST.json").write_text("{}")
    dependency = make_claim(
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.VALID,
        claim_id="dependency-1",
    )
    # Use current time as claim created_at so evidence file (created just above)
    # does not trigger drift detection.
    claim = make_claim(depends_on=[ClaimType.BACKEND_RUNTIME_READY.value], now=None)
    await store.save_claim("project-1", dependency)
    await store.save_claim("project-1", claim)

    result = await validate_claim("project-1", "claim-1", store=store, workspace=str(tmp_path))

    assert result["status"] == "valid"
    assert result["claim"]["status"] == ClaimStatus.VALID.value
    assert result["claim"]["evidence"] == claim["evidence"]
    assert store._redis.published[-1][0] == "project:project-1:events"


@pytest.mark.asyncio
async def test_validate_claim_marks_invalid_when_dependency_fails(tmp_path):
    store = make_store()
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "API_MANIFEST.json").write_text("{}")
    dependency = make_claim(
        claim_type=ClaimType.BACKEND_RUNTIME_READY,
        status=ClaimStatus.INVALID,
        claim_id="dependency-1",
    )
    # Use current time as claim created_at so evidence file does not trigger drift.
    claim = make_claim(depends_on=[ClaimType.BACKEND_RUNTIME_READY.value], now=None)
    await store.save_claim("project-1", dependency)
    await store.save_claim("project-1", claim)

    result = await validate_claim("project-1", "claim-1", store=store, workspace=str(tmp_path))

    assert result["status"] == "invalid"
    assert result["claim"]["status"] == ClaimStatus.INVALID.value
    assert "expected valid" in result["validation"]["errors"][0]


@pytest.mark.asyncio
async def test_revoke_claim_marks_revoked_and_records_reason():
    store = make_store()
    await store.save_claim("project-1", make_claim(status=ClaimStatus.VALID))

    result = await revoke_claim("project-1", "claim-1", "source changed", store=store)

    assert result["status"] == "success"
    assert result["claim"]["status"] == ClaimStatus.REVOKED.value
    assert result["claim"]["validation"]["errors"] == ["source changed"]
    assert store._redis.published[-1][0] == "project:project-1:events"


# ---------------------------------------------------------------------------
# Phase 7: Claim Revocation and Staleness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_claim_warns_on_post_claim_activity():
    """Task 7.1: Event-seq gap produces a warning but not auto-stale without drift."""
    store = make_store()
    claim = make_claim(
        status=ClaimStatus.CLAIMED,
        claim_id="claim-seq",
        producer_event_seq=10,
    )
    await store.save_claim("project-1", claim)
    # Producer has since emitted events up to seq 15 (> 10 + tolerance of 2)
    await store.save_agent_event_seq("project-1", "backend", 15)

    # No evidence files, so it will be invalid; but the warning should be present
    result = await validate_claim("project-1", "claim-seq", store=store, workspace="/nonexistent")

    assert result["status"] == "invalid"
    warnings = result.get("validation", {}).get("warnings") or []
    assert any("Producer activity detected after claim" in w for w in warnings)


@pytest.mark.asyncio
async def test_validate_claim_marks_stale_on_evidence_drift(tmp_path):
    """Evidence drift (file modified after claim) makes claim stale."""
    store = make_store()
    # Create evidence file
    (tmp_path / "backend").mkdir()
    manifest = tmp_path / "backend" / "API_MANIFEST.json"
    manifest.write_text("{}")

    # Claim created at a specific time
    claim = make_claim(
        status=ClaimStatus.CLAIMED,
        claim_id="claim-drift",
        producer_event_seq=10,
        now="2026-05-07T00:00:00Z",
    )
    await store.save_claim("project-1", claim)

    # Simulate producer activity after claim
    await store.save_agent_event_seq("project-1", "backend", 15)

    # Modify the evidence file AFTER the claim time
    import time
    time.sleep(0.01)
    manifest.write_text('{"updated": true}')

    result = await validate_claim("project-1", "claim-drift", store=store, workspace=str(tmp_path))

    assert result["status"] == "stale"
    assert result["claim"]["status"] == ClaimStatus.STALE.value
    assert any("Evidence drift detected" in e for e in result["validation"]["errors"])


@pytest.mark.asyncio
async def test_publish_claim_record_supersedes_previous_claim():
    """Task 7.3: Publishing a new claim of the same type marks the old one stale."""
    store = make_store()
    old_claim = make_claim(
        status=ClaimStatus.VALID,
        claim_id="old-claim",
    )
    await store.save_claim("project-1", old_claim)

    result = await publish_claim_record(
        project_id="project-1",
        producer_agent="backend",
        claim_type=ClaimType.BACKEND_API_READY.value,
        evidence={"files": ["backend/API_MANIFEST.json"]},
        store=store,
    )

    assert result["status"] == "success"
    new_claim = result["claim"]
    assert new_claim["id"] != "old-claim"

    # Old claim should now be stale
    old = await store.get_claim("project-1", "old-claim")
    assert old["status"] == ClaimStatus.STALE.value
    assert "Superseded by newer claim" in old["validation"]["errors"][0]

    # Latest pointer should point to new claim
    latest = await store.get_latest_claim("project-1", ClaimType.BACKEND_API_READY.value)
    assert latest["id"] == new_claim["id"]


@pytest.mark.asyncio
async def test_revoke_claim_cascades_to_dependents():
    """Task 7.2: Revoking a claim marks all dependent claims stale."""
    store = make_store()
    # Setup: BACKEND_API_READY is valid, FRONTEND_BUILD_READY depends on it and is valid
    api_claim = make_claim(
        claim_type=ClaimType.BACKEND_API_READY,
        status=ClaimStatus.VALID,
        claim_id="api-claim",
    )
    build_claim = make_claim(
        claim_type=ClaimType.FRONTEND_BUILD_READY,
        status=ClaimStatus.VALID,
        claim_id="build-claim",
        depends_on=[ClaimType.BACKEND_API_READY.value],
        producer_agent="frontend",
    )
    deploy_claim = make_claim(
        claim_type=ClaimType.DEPLOYMENT_READY,
        status=ClaimStatus.VALID,
        claim_id="deploy-claim",
        depends_on=[
            ClaimType.BACKEND_RUNTIME_READY.value,
            ClaimType.FRONTEND_BUILD_READY.value,
        ],
        producer_agent="devops",
    )
    await store.save_claim("project-1", api_claim)
    await store.save_claim("project-1", build_claim)
    await store.save_claim("project-1", deploy_claim)

    await revoke_claim("project-1", "api-claim", "api contract changed", store=store)

    # Direct dependent FRONTEND_BUILD_READY should be stale
    build = await store.get_claim("project-1", "build-claim")
    assert build["status"] == ClaimStatus.STALE.value
    assert "Dependency BACKEND_API_READY became stale" in build["validation"]["errors"][0]

    # Transitive dependent DEPLOYMENT_READY should also be stale
    deploy = await store.get_claim("project-1", "deploy-claim")
    assert deploy["status"] == ClaimStatus.STALE.value


@pytest.mark.asyncio
async def test_cascade_staleness_idempotent():
    """Cascading twice should not create duplicate errors."""
    store = make_store()
    api_claim = make_claim(
        claim_type=ClaimType.BACKEND_API_READY,
        status=ClaimStatus.VALID,
        claim_id="api-claim",
    )
    build_claim = make_claim(
        claim_type=ClaimType.FRONTEND_BUILD_READY,
        status=ClaimStatus.VALID,
        claim_id="build-claim",
        depends_on=[ClaimType.BACKEND_API_READY.value],
        producer_agent="frontend",
    )
    await store.save_claim("project-1", api_claim)
    await store.save_claim("project-1", build_claim)

    affected1 = await _cascade_staleness(
        "project-1", ClaimType.BACKEND_API_READY.value, "test", store
    )
    assert len(affected1) == 1

    affected2 = await _cascade_staleness(
        "project-1", ClaimType.BACKEND_API_READY.value, "test", store
    )
    assert len(affected2) == 0  # idempotent


@pytest.mark.asyncio
async def test_publish_claim_record_captures_event_seq():
    """Task 7.1: Claims should capture the producer's current event sequence."""
    store = make_store()
    await store.save_agent_event_seq("project-1", "backend", 42)

    result = await publish_claim_record(
        project_id="project-1",
        producer_agent="backend",
        claim_type=ClaimType.BACKEND_API_READY.value,
        store=store,
    )

    claim = result["claim"]
    assert claim["producer_event_seq"] == 42


# ---------------------------------------------------------------------------
# Infrastructure-unavailability: Docker failures must return "skipped", not "failed"
# ---------------------------------------------------------------------------

def _make_go_workspace(tmp_path):
    """Create a minimal Go workspace so _detect_backend_command returns a go build command."""
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "go.mod").write_text("module example.com/app\n\ngo 1.21\n")
    (backend / "main.go").write_text('package main\nfunc main() {}\n')
    return tmp_path


class TestRunVerificationInfrastructureUnavailable:
    """_run_verification must treat Docker infrastructure failures as skipped."""

    @pytest.mark.asyncio
    async def test_image_pull_failure_returns_skipped(self, tmp_path, monkeypatch):
        import src.swarm.tools.claim_tools as ct

        _make_go_workspace(tmp_path)
        monkeypatch.setattr(ct, "_build_tool_available", lambda *a, **kw: False)
        monkeypatch.setattr(ct, "_docker_available", lambda: True)
        monkeypatch.setattr(ct, "_ensure_docker_image", lambda *a, **kw: _async_false())

        result = await _run_verification(
            tmp_path, "backend", "BACKEND_RUNTIME_READY"
        )

        assert result["status"] == "skipped"
        assert "infrastructure_unavailable" in result["reason"]
        assert "could not be pulled" in result["reason"]

    @pytest.mark.asyncio
    async def test_container_creation_timeout_returns_skipped(self, tmp_path, monkeypatch):
        import asyncio
        import src.swarm.tools.claim_tools as ct

        _make_go_workspace(tmp_path)
        monkeypatch.setattr(ct, "_build_tool_available", lambda *a, **kw: False)
        monkeypatch.setattr(ct, "_docker_available", lambda: True)
        monkeypatch.setattr(ct, "_ensure_docker_image", lambda *a, **kw: _async_true())
        monkeypatch.setattr(ct, "_copy_workspace_for_verification", lambda ws: _FakeTempDir(tmp_path))

        call_count = {"n": 0}
        _real_create_subprocess = asyncio.create_subprocess_exec

        async def _slow_create_subprocess(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call is `docker run -d` — make it time out
                class _SlowProc:
                    returncode = 0
                    async def communicate(self):
                        await asyncio.sleep(999)
                return _SlowProc()
            # Subsequent calls (e.g. _cleanup_container) use the real implementation
            return await _real_create_subprocess(*args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _slow_create_subprocess)

        result = await _run_verification(
            tmp_path, "backend", "BACKEND_RUNTIME_READY"
        )

        assert result["status"] == "skipped"
        assert "infrastructure_unavailable" in result["reason"]
        assert "timed out" in result["reason"]

    @pytest.mark.asyncio
    async def test_container_nonzero_exit_returns_skipped(self, tmp_path, monkeypatch):
        import asyncio
        import src.swarm.tools.claim_tools as ct

        _make_go_workspace(tmp_path)
        monkeypatch.setattr(ct, "_build_tool_available", lambda *a, **kw: False)
        monkeypatch.setattr(ct, "_docker_available", lambda: True)
        monkeypatch.setattr(ct, "_ensure_docker_image", lambda *a, **kw: _async_true())
        monkeypatch.setattr(ct, "_copy_workspace_for_verification", lambda ws: _FakeTempDir(tmp_path))

        async def _failing_create_subprocess(*args, **kwargs):
            class _FailProc:
                returncode = 1
                async def communicate(self):
                    return b"", b"docker: Cannot connect to daemon"
            return _FailProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _failing_create_subprocess)

        result = await _run_verification(
            tmp_path, "backend", "BACKEND_RUNTIME_READY"
        )

        assert result["status"] == "skipped"
        assert "infrastructure_unavailable" in result["reason"]


class _FakeTempDir:
    """Minimal tempfile.TemporaryDirectory stand-in for tests."""
    def __init__(self, path):
        import os
        self.name = str(path.parent)
        # Create the expected workspace subdirectory
        ws = path.parent / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        import shutil as _sh
        _sh.copytree(str(path), str(ws), dirs_exist_ok=True)

    def cleanup(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


async def _async_false():
    return False


async def _async_true():
    return True


class TestVerifyAndPublishClaimRecordSkipsGracefully:
    """When _run_verification returns skipped, the claim is still published."""

    @pytest.mark.asyncio
    async def test_publishes_claim_when_verification_skipped(self, tmp_path, monkeypatch):
        import src.swarm.tools.claim_tools as ct

        monkeypatch.setattr(ct, "_workspace_for_project", lambda pid: tmp_path)
        monkeypatch.setattr(ct, "_run_verification", _mock_skipped_verification)

        store = make_store()
        result = await verify_and_publish_claim_record(
            project_id="project-1",
            producer_agent="backend",
            claim_type=ClaimType.BACKEND_RUNTIME_READY.value,
            evidence={"files": []},
            store=store,
        )

        assert result["status"] == "success"
        assert result["verification_skipped"] is True
        assert "infrastructure_unavailable" in (result.get("verification_reason") or "")

        saved = await store.get_latest_claim("project-1", ClaimType.BACKEND_RUNTIME_READY.value)
        assert saved is not None
        assert saved["claim_type"] == ClaimType.BACKEND_RUNTIME_READY.value


async def _mock_skipped_verification(*args, **kwargs):
    return {
        "status": "skipped",
        "reason": "infrastructure_unavailable: Docker image golang:1.24 could not be pulled — claim published without runtime verification",
    }
