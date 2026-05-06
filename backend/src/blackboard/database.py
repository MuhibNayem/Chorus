import os
import json
import asyncpg
from typing import List, Dict, Any, Optional

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/deepseek",
)
RAG_EMBEDDING_DIMENSION = int(os.getenv("RAG_EMBEDDING_DIMENSION", "1536"))


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
                CREATE TABLE IF NOT EXISTS project_checkpoints (
                    id TEXT PRIMARY KEY,
                    project_id UUID REFERENCES projects(id),
                    label TEXT NOT NULL,
                    run_mode TEXT NOT NULL DEFAULT 'generate',
                    trigger_message TEXT,
                    snapshot_path TEXT NOT NULL,
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
                    embedding vector(%d),
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """ % RAG_EMBEDDING_DIMENSION)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS context_summaries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    facts JSONB,
                    preserved_files JSONB,
                    previous_summary_id TEXT,
                    source_event_count INTEGER NOT NULL DEFAULT 0,
                    estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_project_id ON chat_messages(project_id);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_project_checkpoints_project_id
                ON project_checkpoints(project_id, created_at DESC);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_source ON rag_documents(source);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_context_summaries_project_agent
                ON context_summaries(project_id, agent_name, created_at DESC);
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id UUID REFERENCES projects(id),
                    agent_name TEXT NOT NULL,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    files_created JSONB NOT NULL DEFAULT '[]',
                    event_summary JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_checkpoints_project_agent
                ON agent_checkpoints(project_id, agent_name, created_at DESC);
            """)

    async def create_project(self, project_id: str, name: str, spec: Dict[str, Any]) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO projects (id, name, spec, status)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (id) DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), projects.name),
                    spec = EXCLUDED.spec,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                """,
                project_id,
                name,
                json.dumps(spec),
                spec.get("status", "pending"),
            )
        return project_id

    async def ensure_project(
        self,
        project_id: str,
        name: str,
        spec: Optional[Dict[str, Any]] = None,
        status: str = "pending",
    ) -> str:
        await self.create_project(project_id, name, {**(spec or {}), "status": status})
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

    async def update_project_spec(
        self,
        project_id: str,
        spec: Dict[str, Any],
        status: Optional[str] = None,
    ):
        async with self._pool.acquire() as conn:
            if status is None:
                await conn.execute(
                    """
                    UPDATE projects
                    SET spec = $2::jsonb, updated_at = NOW()
                    WHERE id = $1
                    """,
                    project_id,
                    json.dumps(spec),
                )
            else:
                await conn.execute(
                    """
                    UPDATE projects
                    SET spec = $2::jsonb, status = $3, updated_at = NOW()
                    WHERE id = $1
                    """,
                    project_id,
                    json.dumps(spec),
                    status,
                )

    async def list_projects(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM projects
                ORDER BY updated_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

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
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                message_id,
                project_id,
                role,
                content,
                json.dumps(metadata or {}),
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

    async def save_project_checkpoint(
        self,
        checkpoint_id: str,
        project_id: str,
        label: str,
        run_mode: str,
        trigger_message: str,
        snapshot_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO project_checkpoints (
                    id,
                    project_id,
                    label,
                    run_mode,
                    trigger_message,
                    snapshot_path,
                    metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    run_mode = EXCLUDED.run_mode,
                    trigger_message = EXCLUDED.trigger_message,
                    snapshot_path = EXCLUDED.snapshot_path,
                    metadata = EXCLUDED.metadata
                """,
                checkpoint_id,
                project_id,
                label,
                run_mode,
                trigger_message,
                snapshot_path,
                json.dumps(metadata or {}),
            )
        return checkpoint_id

    async def list_project_checkpoints(
        self,
        project_id: str,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM project_checkpoints
                WHERE project_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                project_id,
                limit,
            )
            return [dict(row) for row in rows]

    async def get_project_checkpoint(
        self,
        project_id: str,
        checkpoint_id: str,
    ) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM project_checkpoints
                WHERE project_id = $1 AND id = $2
                """,
                project_id,
                checkpoint_id,
            )
            return dict(row) if row else None

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
        embedding_str = json.dumps(embedding)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO rag_embeddings (document_id, embedding)
                VALUES ($1, $2::vector)
                """,
                document_id,
                embedding_str,
            )

    async def search_rag(
        self, query_embedding: List[float], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        embedding_str = json.dumps(query_embedding)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    d.id,
                    d.source,
                    d.chunk_text,
                    d.metadata,
                    1 - (e.embedding <=> $1::vector) as similarity
                FROM rag_embeddings e
                JOIN rag_documents d ON e.document_id = d.id
                ORDER BY e.embedding <=> $1::vector
                LIMIT $2
                """,
                embedding_str,
                top_k,
            )
            return [dict(row) for row in rows]

    async def search_rag_filtered(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        source_filter: str = "",
    ) -> List[Dict[str, Any]]:
        embedding_str = json.dumps(query_embedding)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    d.id,
                    d.source,
                    d.chunk_text,
                    d.metadata,
                    1 - (e.embedding <=> $1::vector) as similarity
                FROM rag_embeddings e
                JOIN rag_documents d ON e.document_id = d.id
                WHERE d.source = $3
                ORDER BY e.embedding <=> $1::vector
                LIMIT $2
                """,
                embedding_str,
                top_k,
                source_filter,
            )
            return [dict(row) for row in rows]

    async def save_context_summary(
        self,
        summary_id: str,
        project_id: str,
        agent_name: str,
        summary: str,
        facts: Optional[Dict[str, Any]] = None,
        preserved_files: Optional[List[str]] = None,
        previous_summary_id: Optional[str] = None,
        source_event_count: int = 0,
        estimated_tokens: int = 0,
    ) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO context_summaries (
                    id,
                    project_id,
                    agent_name,
                    summary,
                    facts,
                    preserved_files,
                    previous_summary_id,
                    source_event_count,
                    estimated_tokens
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9)
                ON CONFLICT (id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    facts = EXCLUDED.facts,
                    preserved_files = EXCLUDED.preserved_files,
                    previous_summary_id = EXCLUDED.previous_summary_id,
                    source_event_count = EXCLUDED.source_event_count,
                    estimated_tokens = EXCLUDED.estimated_tokens,
                    updated_at = NOW()
                """,
                summary_id,
                project_id,
                agent_name,
                summary,
                json.dumps(facts or {}),
                json.dumps(preserved_files or []),
                previous_summary_id,
                source_event_count,
                estimated_tokens,
            )
        return summary_id

    async def get_latest_context_summary(
        self,
        project_id: str,
        agent_name: str,
    ) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM context_summaries
                WHERE project_id = $1 AND agent_name = $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                project_id,
                agent_name,
            )
            return dict(row) if row else None

    async def get_context_summary_chain(
        self,
        project_id: str,
        agent_name: str,
        max_chain_length: int = 10,
    ) -> List[Dict[str, Any]]:
        chain = []
        current_id = None
        async with self._pool.acquire() as conn:
            for _ in range(max_chain_length):
                if current_id is None:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM context_summaries
                        WHERE project_id = $1 AND agent_name = $2
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        project_id,
                        agent_name,
                    )
                else:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM context_summaries
                        WHERE id = $1
                        """,
                        current_id,
                    )
                if not row:
                    break
                chain.append(dict(row))
                current_id = row.get("previous_summary_id")
                if not current_id:
                    break
        return chain

    async def list_context_summaries(
        self,
        project_id: str,
        agent_name: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if agent_name:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_summaries
                    WHERE project_id = $1 AND agent_name = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    project_id,
                    agent_name,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM context_summaries
                    WHERE project_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    project_id,
                    limit,
                )
            return [dict(row) for row in rows]

    async def save_agent_checkpoint(
        self,
        project_id: str,
        agent_name: str,
        iteration: int,
        files_created: str,
        event_summary: str,
    ) -> str:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agent_checkpoints (
                    project_id,
                    agent_name,
                    iteration,
                    files_created,
                    event_summary
                )
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                RETURNING id
                """,
                project_id,
                agent_name,
                iteration,
                files_created,
                event_summary,
            )
            return str(row["id"])

    async def get_latest_agent_checkpoint(
        self,
        project_id: str,
        agent_name: str,
    ) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM agent_checkpoints
                WHERE project_id = $1 AND agent_name = $2
                ORDER BY iteration DESC, created_at DESC
                LIMIT 1
                """,
                project_id,
                agent_name,
            )
            return dict(row) if row else None

    async def list_agent_checkpoints(
        self,
        project_id: str,
        agent_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if agent_name:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_checkpoints
                    WHERE project_id = $1 AND agent_name = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    project_id,
                    agent_name,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_checkpoints
                    WHERE project_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    project_id,
                    limit,
                )
            return [dict(row) for row in rows]
