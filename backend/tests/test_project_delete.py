"""Tests for complete project deletion."""

import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    return ws


@pytest.fixture
def tmp_checkpoint(tmp_path):
    cp = tmp_path / "checkpoints"
    cp.mkdir()
    return cp


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.pubsub_channels = {}

    async def ping(self):
        pass

    async def aclose(self):
        pass

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)

    async def exists(self, key):
        return 1 if key in self.data else 0

    async def sadd(self, key, *values):
        s = self.data.setdefault(key, set())
        s.update(values)

    async def smembers(self, key):
        return self.data.get(key, set())

    async def publish(self, channel, message):
        pass

    async def zadd(self, key, mapping):
        self.data[key] = list(mapping.keys())

    async def zremrangebyscore(self, key, min_score, max_score):
        pass

    async def zcard(self, key):
        return len(self.data.get(key, []))

    async def zrange(self, key, start, end):
        return self.data.get(key, [])

    async def expire(self, key, seconds):
        pass

    async def scan(self, cursor, match=None, count=None):
        keys = [k for k in self.data if match is None or match in k]
        return 0, keys


class FakePool:
    def __init__(self):
        self._queries = []

    async def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, query, *args):
        self._queries.append((query, args))

    async def fetch(self, query, *args):
        self._queries.append((query, args))
        return []

    async def fetchrow(self, query, *args):
        self._queries.append((query, args))
        return None

    async def transaction(self):
        class Txn:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        return Txn()


class FakeDatabase:
    def __init__(self):
        self._pool = FakePool()
        self.deleted_project = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def init_schema(self):
        pass

    async def delete_project(self, project_id: str) -> bool:
        self.deleted_project = project_id
        return True


class FakeMinioStorage:
    def __init__(self):
        self.deleted_prefix = None

    async def connect(self):
        pass

    async def delete_objects_by_prefix(self, prefix: str):
        self.deleted_prefix = prefix
        return {"status": "success", "deleted": [], "count": 0}


def test_delete_project_endpoint_rejects_running_project(monkeypatch, tmp_path):
    """DELETE should return 409 if project is currently running."""
    from fastapi.testclient import TestClient

    # Patch workspace/checkpoint bases
    monkeypatch.setattr("src.main.WORKSPACE_BASE", tmp_path / "workspaces")
    monkeypatch.setattr("src.main.CHECKPOINT_BASE", tmp_path / "checkpoints")

    fake_redis = FakeRedis()
    fake_redis.data["project:proj-123:state"] = '{"status": "running"}'

    fake_blackboard = MagicMock()
    fake_blackboard.get_project_state = AsyncMock(return_value={"status": "running"})

    fake_db = FakeDatabase()
    fake_storage = FakeMinioStorage()

    with patch("src.main.blackboard", fake_blackboard), \
         patch("src.main.database", fake_db), \
         patch("src.main.storage", fake_storage):
        from src.main import app
        client = TestClient(app)
        response = client.delete("/api/projects/proj-123")

    assert response.status_code == 409
    data = response.json()
    assert data["error"] == "Cannot delete a running project"


def test_delete_project_endpoint_cleans_up_all_data(monkeypatch, tmp_path):
    """DELETE should clean up DB, Redis, filesystem, and MinIO."""
    from fastapi.testclient import TestClient

    ws = tmp_path / "workspaces" / "proj-456"
    ws.mkdir(parents=True)
    (ws / "test.py").write_text("print('hello')")

    cp = tmp_path / "checkpoints" / "proj-456"
    cp.mkdir(parents=True)
    (cp / "snap.zip").write_text("zipdata")

    monkeypatch.setattr("src.main.WORKSPACE_BASE", tmp_path / "workspaces")
    monkeypatch.setattr("src.main.CHECKPOINT_BASE", tmp_path / "checkpoints")

    fake_blackboard = MagicMock()
    fake_blackboard.get_project_state = AsyncMock(return_value={"status": "complete"})
    fake_blackboard.delete_project_keys = AsyncMock(return_value=5)

    fake_db = FakeDatabase()
    fake_storage = FakeMinioStorage()

    with patch("src.main.blackboard", fake_blackboard), \
         patch("src.main.database", fake_db), \
         patch("src.main.storage", fake_storage):
        from src.main import app
        client = TestClient(app)
        response = client.delete("/api/projects/proj-456")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert data["project_id"] == "proj-456"
    assert data["deleted"]["database"] is True
    assert data["deleted"]["redis"] == 5
    assert data["deleted"]["filesystem_workspace"] is True
    assert data["deleted"]["filesystem_checkpoints"] is True
    assert fake_storage.deleted_prefix == "checkpoints/proj-456/"

    # Verify filesystem is actually gone
    assert not ws.exists()
    assert not cp.exists()


def test_delete_project_endpoint_handles_missing_project(monkeypatch, tmp_path):
    """DELETE should succeed even if project data is partially missing."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr("src.main.WORKSPACE_BASE", tmp_path / "workspaces")
    monkeypatch.setattr("src.main.CHECKPOINT_BASE", tmp_path / "checkpoints")

    fake_blackboard = MagicMock()
    fake_blackboard.get_project_state = AsyncMock(return_value=None)
    fake_blackboard.delete_project_keys = AsyncMock(return_value=0)

    fake_db = FakeDatabase()
    fake_storage = FakeMinioStorage()

    with patch("src.main.blackboard", fake_blackboard), \
         patch("src.main.database", fake_db), \
         patch("src.main.storage", fake_storage):
        from src.main import app
        client = TestClient(app)
        response = client.delete("/api/projects/proj-789")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert data["deleted"]["database"] is True
