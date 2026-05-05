import os
import json
import asyncpg
from typing import List, Dict, Any, Optional
from datetime import datetime
import numpy as np

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/deepseek",
)


class Database:
    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
        )

    async def disconnect(self):
        if self._pool:
            await self._pool.close()

    async def init_schema(self):
        if not self._pool:
            await self.connect()

        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE EXTENSION IF NOT EXISTS vector;
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    spec JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id UUID PRIMARY KEY,
                    project_id UUID REFERENCES projects(id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id SERIAL PRIMARY KEY,
                    source TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_embeddings (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER REFERENCES rag_documents(id) ON DELETE CASCADE,
                    embedding vector(1024),
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_project_id ON chat_messages(project_id);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_source ON rag_documents(source);
            """)

    async def create_project(self, project_id: str, name: str, spec: Dict[str, Any]) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO projects (id, name, spec)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    spec = EXCLUDED.spec,
                    updated_at = NOW()
                """,
                project_id,
                name,
                json.dumps(spec),
            )
        return project_id

    async def update_project_status(self, project_id: str, status: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE projects SET status = $2, updated_at = NOW()
                WHERE id = $1
                """,
                project_id,
                status,
            )

    async def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM projects WHERE id = $1
                """,
                project_id,
            )
            if row:
                return dict(row)
        return None

    async def save_chat_message(
        self,
        message_id: str,
        project_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_messages (id, project_id, role, content, metadata)
                VALUES ($1, $2, $3, $4, $5)
                """,
                message_id,
                project_id,
                role,
                content,
                metadata,
            )

    async def get_chat_messages(self, project_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM chat_messages
                WHERE project_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                project_id,
                limit,
            )
            return [dict(row) for row in rows]

    async def add_rag_document(
        self,
        source: str,
        chunk_text: str,
        chunk_index: int,
        metadata: Optional[Dict] = None,
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rag_documents (source, chunk_text, chunk_index, metadata)
                VALUES ($1, $2, $3, $4::jsonb)
                RETURNING id
                """,
                source,
                chunk_text,
                chunk_index,
                json.dumps(metadata) if metadata else None,
            )
            return row["id"]

    async def add_rag_embedding(self, document_id: int, embedding: List[float]):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO rag_embeddings (document_id, embedding)
                VALUES ($1, $2)
                """,
                document_id,
                embedding,
            )

    async def search_rag(
        self, query_embedding: List[float], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    d.id,
                    d.source,
                    d.chunk_text,
                    d.metadata,
                    1 - (e.embedding <=> $1) as similarity
                FROM rag_embeddings e
                JOIN rag_documents d ON e.document_id = d.id
                ORDER BY e.embedding <=> $1
                LIMIT $2
                """,
                embedding,
                top_k,
            )
            return [dict(row) for row in rows]
