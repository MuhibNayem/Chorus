import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.agents import AgentSwarm
from src.swarm.claim_store import ClaimStore
from src.swarm.claims import ClaimStatus, ClaimType, build_claim_payload
from src.swarm.tools.claim_tools import publish_claim_record
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
        removed = sum(1 for score, _ in entries if min_val <= score <= max_val)
        self.zsets[key] = [
            (score, member)
            for score, member in entries
            if not (min_val <= score <= max_val)
        ]
        return removed

    async def zcard(self, key):
        return len(self.zsets.get(key, []))

    async def zrange(self, key, start, end):
        entries = self.zsets.get(key, [])
        if end == -1:
            end = None
        else:
            end = end + 1
        return [member for _, member in entries[start:end]]

    async def expire(self, key, seconds):
        return True


@pytest.mark.asyncio
async def test_ensure_valid_claim_repairs_frontend_claim_with_canonical_evidence(tmp_path):
    import src.swarm.tools.workspace_tools as wtools

    project_id = "project-frontend-repair"
    workspace = tmp_path / project_id
    workspace.mkdir(parents=True)

    (workspace / "SPEC.md").write_text("# Spec\n")
    frontend_dir = workspace / "frontend"
    src_dir = frontend_dir / "src"
    src_dir.mkdir(parents=True)
    (frontend_dir / "package.json").write_text(
        """
        {
          "scripts": {"build": "vite build"},
          "dependencies": {"vite": "^5.0.0"}
        }
        """.strip()
    )
    (src_dir / "main.ts").write_text("console.log('hello');\n")

    orig_base = wtools.WORKSPACE_BASE
    wtools.WORKSPACE_BASE = tmp_path
    try:
        set_project_context(project_id)
        redis = FakeRedis()
        store = ClaimStore(redis_client=redis, ttl_seconds=100)
        spec_claim = build_claim_payload(
            project_id=project_id,
            claim_type=ClaimType.SPEC_READY,
            producer_agent="rootdep",
            evidence={"files": ["SPEC.md"]},
            status=ClaimStatus.VALID,
        )
        await store.save_claim(project_id, spec_claim)

        await publish_claim_record(
            project_id=project_id,
            producer_agent="frontend",
            claim_type=ClaimType.FRONTEND_SOURCE_READY.value,
            evidence={"files": ["frontend/package.json"]},
            store=store,
        )

        swarm = AgentSwarm()
        swarm.project_id = project_id
        swarm.claim_store_factory = lambda: store

        ok, error = await swarm._ensure_valid_claim(ClaimType.FRONTEND_SOURCE_READY.value)
        assert ok is True
        assert error == ""

        verify_store = ClaimStore(redis_client=redis, ttl_seconds=100)
        try:
            latest = await verify_store.get_latest_claim(project_id, ClaimType.FRONTEND_SOURCE_READY.value)
            assert latest is not None
            assert sorted(latest["evidence"]["files"]) == [
                "frontend/package.json",
                "frontend/src/main.ts",
            ]
        finally:
            await verify_store.close()
    finally:
        wtools.WORKSPACE_BASE = orig_base
        await store.close()
