import asyncio
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("context")

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/deepseek/workspaces"))
DEFAULT_CONTEXT_MODE = "auto"
RULES_CHAR_LIMIT = int(os.getenv("CONTEXT_RULES_CHAR_LIMIT", "32768"))
USER_REQUEST_TOKEN_LIMIT = int(os.getenv("CONTEXT_USER_REQUEST_TOKEN_LIMIT", "3000"))
USER_REQUEST_QUERY_TOKEN_LIMIT = int(os.getenv("CONTEXT_USER_REQUEST_QUERY_TOKEN_LIMIT", "1000"))

# Tokenizer: cl100k_base approximates MiniMax M2.7 but is not exact.
# Set TOKENIZER_ENCODING to override. TOKEN_SAFETY_FACTOR adds a conservative
# margin to compensate for tokenizer divergence.
TOKENIZER_ENCODING = os.getenv("TOKENIZER_ENCODING", "cl100k_base")
TOKEN_SAFETY_FACTOR = float(os.getenv("TOKEN_SAFETY_FACTOR", "1.1"))

# Workspace snapshot cache — avoids redundant filesystem scans within one run.
# Invalidated by write_file via invalidate_snapshot_cache().
SNAPSHOT_CACHE_TTL = int(os.getenv("CONTEXT_SNAPSHOT_CACHE_TTL", "30"))

import tiktoken


@dataclass
class _SnapshotCacheEntry:
    snapshot: str
    file_count: int
    files: List[str]
    expires_at: float


_snapshot_cache: Dict[Tuple[str, str], _SnapshotCacheEntry] = {}


def invalidate_snapshot_cache(project_id: str) -> None:
    """Invalidate all snapshot cache entries for a project.

    Called by write_file whenever a file is successfully written so the next
    context build reflects the latest workspace state.
    """
    stale = [k for k in _snapshot_cache if k[0] == project_id]
    for k in stale:
        del _snapshot_cache[k]


class TokenEstimator:
    """Token estimator using tiktoken with a configurable safety factor.

    NOTE: TOKENIZER_ENCODING defaults to cl100k_base (GPT-4 family).  MiniMax
    M2.7 uses its own tokenizer; estimates may diverge by 10-40 %.  TOKEN_SAFETY_FACTOR
    (default 1.1) adds a conservative margin.  Set TOKENIZER_ENCODING via env var
    when a closer tokenizer becomes available.
    """

    def __init__(self, encoding_name: str = TOKENIZER_ENCODING):
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning(
                "Failed to load tiktoken encoding %s, falling back to cl100k_base: %s",
                encoding_name,
                e,
            )
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def estimate(self, value: Any) -> int:
        if value is None:
            return 0
        if not isinstance(value, str):
            value = json.dumps(value, default=str)
        try:
            raw = len(self.encoding.encode(value))
        except Exception as e:
            logger.warning("Token estimation failed: %s. Using heuristic.", e)
            raw = max(1, math.ceil(len(value) / 3.0))
        return max(1, math.ceil(raw * TOKEN_SAFETY_FACTOR))


@dataclass
class ContextPolicy:
    mode: str
    max_tokens: int
    compact_threshold: int
    rag_top_k: int
    file_excerpt_chars: int
    event_budget_tokens: int

    @classmethod
    def for_agent(cls, agent_name: str, mode: str = DEFAULT_CONTEXT_MODE) -> "ContextPolicy":
        mode = mode if mode in {"auto", "lean", "full"} else DEFAULT_CONTEXT_MODE
        base_max = {
            "rootdep": 256000,
            "backend": 256000,
            "frontend": 256000,
            "devops": 256000,
            "packager": 256000,
        }.get(agent_name, 256000)

        if mode == "lean":
            max_tokens = int(base_max * 0.5)
            rag_top_k = 5
            file_excerpt_chars = 10000
        elif mode == "full":
            max_tokens = base_max
            rag_top_k = 15
            file_excerpt_chars = 20000
        else:  # auto — conservative middle ground
            max_tokens = base_max
            rag_top_k = 10
            file_excerpt_chars = 15000

        return cls(
            mode=mode,
            max_tokens=max_tokens,
            compact_threshold=int(max_tokens * 0.85),
            rag_top_k=rag_top_k,
            file_excerpt_chars=file_excerpt_chars,
            event_budget_tokens=int(max_tokens * 0.1),
        )


@dataclass
class BuiltContext:
    content: str
    estimated_tokens: int
    compacted: bool
    rag_chunks: int
    file_excerpt_count: int
    summary_id: Optional[str]
    sources: List[str]


class LLMSummarizer:
    """Summarizes long context sections via the LLM to preserve semantic content.

    Falls back to mechanical head+tail truncation if the LLM is unavailable or
    fails.  The LLM is lazily initialised to avoid import-time side effects.
    """

    # Hard cap on input to LLM to avoid runaway costs on enormous sections.
    _MAX_INPUT_CHARS = 60_000

    def __init__(self, llm: Optional[Any] = None):
        self._llm = llm
        self._available = llm is not None

    def _get_llm(self) -> Optional[Any]:
        if self._llm is not None:
            return self._llm
        try:
            from ..llm.minimax import create_minimax_client
            self._llm = create_minimax_client()
            self._available = True
        except Exception as e:
            logger.warning("[LLMSummarizer] Cannot initialise LLM: %s", e)
            self._available = False
        return self._llm

    async def summarize(self, text: str, section_name: str, max_tokens: int) -> Optional[str]:
        """Return an LLM-generated summary of *text* targeting *max_tokens*.

        Returns None on failure so the caller can fall back to mechanical truncation.
        """
        llm = self._get_llm()
        if not llm:
            return None

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            prompt = (
                f"Summarise the following '{section_name}' for an AI coding agent context window.\n"
                "Preserve ALL of: file paths, function/class/method names, API endpoints, "
                "configuration keys, error messages, import statements, build commands, "
                "data model fields, and constraints.\n"
                f"Target length: under {max_tokens} tokens.  Return only the summary — no preamble.\n\n"
                f"{text[: self._MAX_INPUT_CHARS]}"
            )
            messages = [
                SystemMessage(
                    content=(
                        "You are a technical context summariser. Be concise. "
                        "Preserve every actionable technical detail."
                    )
                ),
                HumanMessage(content=prompt),
            ]
            result = await llm.ainvoke(messages)
            summary = result.content if hasattr(result, "content") else str(result)
            return summary.strip() or None
        except Exception as e:
            logger.warning("[LLMSummarizer] LLM summarisation failed for %s: %s", section_name, e)
            return None


class ContextCompactor:
    def __init__(
        self,
        estimator: Optional[TokenEstimator] = None,
        llm_summarizer: Optional[LLMSummarizer] = None,
    ):
        self.estimator = estimator or TokenEstimator()
        self.llm_summarizer = llm_summarizer or LLMSummarizer()

    async def compact_sections(
        self,
        sections: Dict[str, str],
        policy: ContextPolicy,
    ) -> Tuple[Dict[str, str], Optional[Dict[str, Any]]]:
        rendered = self.render_sections(sections)
        if self.estimator.estimate(rendered) <= policy.compact_threshold:
            return sections, None

        compacted = dict(sections)
        before_tokens = self.estimator.estimate(rendered)
        compacted_section_names: List[str] = []

        # --- Pass 1: LLM summarise (or mechanical fallback) for 3 priority sections ---
        for key in ("Relevant Knowledge", "Workspace Snapshot", "Project Rules"):
            value = compacted.get(key, "")
            if not value:
                continue
            current_tokens = self.estimator.estimate(self.render_sections(compacted))
            over_by = current_tokens - policy.compact_threshold
            if over_by <= 0:
                break

            section_token_budget = max(
                500,
                self.estimator.estimate(value) - over_by - 100,
            )
            summary = await self.llm_summarizer.summarize(value, key, section_token_budget)
            if summary is None:
                # Mechanical fallback
                max_chars = max(1200, policy.file_excerpt_chars // 2)
                summary = self._truncate_text(value, max_chars)

            compacted[key] = summary
            compacted_section_names.append(key)

            if self.estimator.estimate(self.render_sections(compacted)) <= policy.compact_threshold:
                break

        # --- Pass 2: Emergency aggressive truncation if still over budget ---
        remaining = self.estimator.estimate(self.render_sections(compacted)) - policy.compact_threshold
        if remaining > 0:
            logger.warning(
                "[ContextCompactor] Still %d tokens over threshold after pass-1; "
                "applying emergency truncation to all sections.",
                remaining,
            )
            for key in (
                "Previous Context Summary Chain",
                "Recent Chat History",
                "Dependency Signals",
                "Relevant Knowledge",
                "Workspace Snapshot",
                "Project Rules",
                "Agent Task",
            ):
                value = compacted.get(key, "")
                if not value:
                    continue
                current = self.estimator.estimate(self.render_sections(compacted))
                if current <= policy.compact_threshold:
                    break
                over_by = current - policy.compact_threshold
                current_section_tokens = self.estimator.estimate(value)
                target_chars = max(300, len(value) - int(over_by * 4))
                compacted[key] = self._truncate_text(value, target_chars)
                if key not in compacted_section_names:
                    compacted_section_names.append(key)

        after_tokens = self.estimator.estimate(self.render_sections(compacted))
        if after_tokens > policy.max_tokens:
            logger.error(
                "[ContextCompactor] Context still exceeds max_tokens after full compaction "
                "(%d > %d). Proceeding — agent may encounter a provider context-length error.",
                after_tokens,
                policy.max_tokens,
            )

        return compacted, {
            "summary": (
                f"Context compacted: {before_tokens}→{after_tokens} tokens "
                f"({round((1 - after_tokens / before_tokens) * 100, 1)}% reduction). "
                f"Sections compacted: {', '.join(compacted_section_names) or 'none'}."
            ),
            "facts": {
                "compacted_sections": compacted_section_names,
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "reduction_pct": round((1 - after_tokens / max(before_tokens, 1)) * 100, 1),
                "mode": policy.mode,
            },
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
        }

    def compact_user_request(
        self,
        text: str,
        max_tokens: int = USER_REQUEST_TOKEN_LIMIT,
    ) -> str:
        if not text:
            return ""
        token_count = self.estimator.estimate(text)
        if token_count <= max_tokens:
            return text

        # Scale char slices proportionally to the token overage.
        ratio = max_tokens / token_count
        total_chars = max(1800, int(len(text) * ratio))
        head_chars = max(1200, int(total_chars * 0.65))
        tail_chars = max(600, total_chars - head_chars)
        head = text[:head_chars].strip()
        tail = text[-tail_chars:].strip()

        return (
            f"[User request compacted from {len(text)} chars / {token_count} tokens]\n"
            "Preserve all explicit requirements, constraints, and acceptance criteria from the original request.\n\n"
            "[Beginning]\n"
            f"{head}\n\n"
            "[Middle omitted for context budget]\n\n"
            "[Ending]\n"
            f"{tail}"
        )

    def compact_user_request_for_query(
        self,
        text: str,
        max_tokens: int = USER_REQUEST_QUERY_TOKEN_LIMIT,
    ) -> str:
        if not text:
            return ""
        token_count = self.estimator.estimate(text)
        if token_count <= max_tokens:
            return text

        ratio = max_tokens / token_count
        total_chars = max(1100, int(len(text) * ratio))
        head_chars = max(800, int(total_chars * 0.75))
        tail_chars = max(300, total_chars - head_chars)
        return (
            f"{text[:head_chars].strip()}\n\n"
            "[Query compacted]\n\n"
            f"{text[-tail_chars:].strip()}"
        )

    def compact_events(
        self,
        events: List[Dict[str, Any]],
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        tool_names: List[str] = []
        errors: List[str] = []
        notes: List[str] = []

        for event in events:
            etype = event.get("type", "")
            if etype == "tool_call":
                tool = event.get("tool") or event.get("name") or "unknown"
                if tool not in tool_names:
                    tool_names.append(tool)
            if etype == "error":
                errors.append(str(event.get("content", ""))[:500])
            content = str(event.get("content", "")).strip()
            if content:
                notes.append(content[:500])

        summary = "\n".join(notes)
        # Convert token budget to an approximate character budget (4 chars/token).
        max_chars = max_tokens * 4
        if len(summary) > max_chars:
            summary = summary[:max_chars] + "\n[Event summary truncated]"

        return {
            "summary": summary or "No event details captured.",
            "facts": {
                "tool_names": tool_names,
                "errors": errors,
                "event_count": len(events),
            },
        }

    def render_sections(self, sections: Dict[str, str]) -> str:
        parts = []
        for name, value in sections.items():
            if value:
                parts.append(f"## {name}\n{value.strip()}")
        return "\n\n".join(parts)

    def _truncate_text(self, text: str, max_chars: int) -> str:
        """Mechanical head+tail truncation used as a fallback when LLM is unavailable."""
        if len(text) <= max_chars:
            return text
        head = text[: max_chars // 2].strip()
        tail = text[-max_chars // 2 :].strip()
        return (
            "[Compacted — head/tail preserved]\n"
            f"{head}\n\n"
            "[Middle omitted during context compaction]\n\n"
            f"{tail}"
        )


class ContextRetriever:
    def __init__(self, project_id: str, database=None, rag_pipeline=None, blackboard=None):
        self.project_id = project_id
        self.database = database
        self.rag_pipeline = rag_pipeline
        self.blackboard = blackboard

    async def get_latest_summary(self, agent_name: str) -> Optional[Dict[str, Any]]:
        if not self.database or not getattr(self.database, "_pool", None):
            return None
        try:
            return await self.database.get_latest_context_summary(self.project_id, agent_name)
        except Exception as e:
            logger.warning("[ContextRetriever] Failed to load latest summary: %s", e)
            return None

    async def get_summary_chain(self, agent_name: str, max_length: int = 10) -> List[Dict[str, Any]]:
        if not self.database or not getattr(self.database, "_pool", None):
            return []
        try:
            return await self.database.get_context_summary_chain(self.project_id, agent_name, max_length)
        except Exception as e:
            logger.warning("[ContextRetriever] Failed to load summary chain: %s", e)
            return []

    async def get_chat_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.database or not getattr(self.database, "_pool", None):
            return []
        try:
            return await self.database.get_chat_messages(self.project_id, limit=limit)
        except Exception as e:
            logger.warning("[ContextRetriever] Failed to load chat history: %s", e)
            return []

    async def get_dependency_state(self) -> str:
        if not self.blackboard:
            return ""
        try:
            state = await self.blackboard.get_project_state(self.project_id)
            if not state:
                return ""
            return json.dumps(state, default=str, indent=2)[:4000]
        except Exception as e:
            logger.warning("[ContextRetriever] Failed to load dependency state: %s", e)
            return ""

    async def get_rag_context(self, agent_name: str, query: str, top_k: int) -> Tuple[str, int, List[str]]:
        if not self.rag_pipeline or not self.database:
            return "", 0, []

        sources = self._rag_sources_for_agent(agent_name)
        chunks: List[str] = []
        used_sources: List[str] = []

        try:
            self.rag_pipeline.set_database(self.database)
            if not sources:
                results = await self.rag_pipeline.retrieve_knowledge(query, top_k=top_k)
            else:
                results = []
                per_source = max(1, math.ceil(top_k / len(sources)))
                for source in sources:
                    source_results = await self.rag_pipeline.retrieve_knowledge(
                        query,
                        top_k=per_source,
                        source_filter=source,
                    )
                    results.extend(source_results)

            for result in results[:top_k]:
                source = result.get("source", "unknown")
                chunk = result.get("chunk_text", "")
                if chunk:
                    used_sources.append(source)
                    chunks.append(f"[{source}] {chunk}")
        except Exception as e:
            logger.warning("[ContextRetriever] RAG unavailable for %s: %s", agent_name, e)
            return "", 0, []

        return "\n\n".join(chunks), len(chunks), sorted(set(used_sources))

    async def get_workspace_snapshot(
        self, agent_name: str, excerpt_chars: int
    ) -> Tuple[str, int, List[str]]:
        """Return a workspace snapshot, using a short-TTL cache to avoid redundant I/O.

        Cache is invalidated by invalidate_snapshot_cache() whenever write_file succeeds.
        """
        cache_key = (self.project_id, agent_name)
        entry = _snapshot_cache.get(cache_key)
        if entry and time.monotonic() < entry.expires_at:
            logger.debug(
                "[ContextRetriever] Snapshot cache hit for %s/%s", self.project_id, agent_name
            )
            return entry.snapshot, entry.file_count, entry.files

        snapshot, file_count, files = await asyncio.to_thread(
            self._get_workspace_snapshot_sync, agent_name, excerpt_chars
        )
        _snapshot_cache[cache_key] = _SnapshotCacheEntry(
            snapshot=snapshot,
            file_count=file_count,
            files=files,
            expires_at=time.monotonic() + SNAPSHOT_CACHE_TTL,
        )
        return snapshot, file_count, files

    def _get_workspace_snapshot_sync(
        self, agent_name: str, excerpt_chars: int
    ) -> Tuple[str, int, List[str]]:
        workspace = WORKSPACE_BASE / self.project_id
        if not workspace.exists():
            return "Workspace is empty or not created yet.", 0, []

        priority = self._priority_files_for_agent(agent_name)
        file_paths = [path for path in priority if (workspace / path).is_file()]

        if not file_paths:
            file_paths = [
                str(path.relative_to(workspace))
                for path in sorted(workspace.rglob("*"))
                if path.is_file() and not path.name.endswith(".zip")
            ][:20]

        snippets: List[str] = []
        used: List[str] = []
        per_file_chars = max(1000, excerpt_chars // max(1, min(len(file_paths), 5)))

        for rel in file_paths[:8]:
            path = workspace / rel
            try:
                text = path.read_text(errors="replace")
            except Exception:
                continue
            if len(text) > per_file_chars:
                text = text[:per_file_chars] + "\n[File excerpt truncated]"
            snippets.append(f"### {rel}\n{text}")
            used.append(rel)

        manifest = "\n".join(file_paths[:80])
        snapshot = f"Files:\n{manifest}\n\n" + "\n\n".join(snippets)
        return snapshot.strip(), len(used), used

    def get_project_rules(self) -> str:
        repo_root = Path(__file__).resolve().parents[3]
        candidates = [
            repo_root / "AGENTS.md",
            repo_root / "CLAUDE.md",
            repo_root / "docs" / "SPEC.md",
        ]
        parts: List[str] = []
        total = 0
        for path in candidates:
            if not path.is_file():
                continue
            text = path.read_text(errors="replace")
            remaining = RULES_CHAR_LIMIT - total
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining] + "\n[Project rules truncated]"
            parts.append(f"### {path.relative_to(repo_root)}\n{text}")
            total += len(text)
        return "\n\n".join(parts)

    def _rag_sources_for_agent(self, agent_name: str) -> List[str]:
        return {
            "backend": ["knowledge_base/spring_boot", "knowledge_base/architecture"],
            "frontend": ["knowledge_base/svelte", "knowledge_base/architecture"],
            "devops": ["knowledge_base/architecture"],
            "packager": [],
            "rootdep": [],
        }.get(agent_name, [])

    def _priority_files_for_agent(self, agent_name: str) -> List[str]:
        common = ["SPEC.md", "README.md", "docker-compose.yml"]
        per_agent = {
            "backend": ["backend/pom.xml", "backend/src/main/resources/application.yml"],
            "frontend": ["frontend/package.json", "frontend/src/routes/+page.svelte"],
            "devops": ["backend/Dockerfile", "frontend/Dockerfile", "nginx/nginx.conf"],
            "packager": ["backend/pom.xml", "frontend/package.json", "docker-compose.yml"],
            "rootdep": [],
        }
        return common + per_agent.get(agent_name, [])


class ContextBuilder:
    def __init__(self, database=None, rag_pipeline=None, blackboard=None, llm=None):
        self.database = database
        self.rag_pipeline = rag_pipeline
        self.blackboard = blackboard
        self.estimator = TokenEstimator()
        self.llm_summarizer = LLMSummarizer(llm=llm)
        self.compactor = ContextCompactor(self.estimator, self.llm_summarizer)

    async def build_agent_input(
        self,
        project_id: str,
        agent_name: str,
        user_request: str,
        task: str,
        context_mode: str = DEFAULT_CONTEXT_MODE,
    ) -> BuiltContext:
        policy = ContextPolicy.for_agent(agent_name, context_mode)
        retriever = ContextRetriever(project_id, self.database, self.rag_pipeline, self.blackboard)

        compact_user_request = self.compactor.compact_user_request(user_request)
        compact_task = self.compactor.compact_user_request(task)
        query_request = self.compactor.compact_user_request_for_query(user_request)

        (
            summary_chain,
            dependency_state,
            (rag_context, rag_count, rag_sources),
            (workspace_snapshot, file_count, files),
            project_rules,
            chat_history,
        ) = await asyncio.gather(
            retriever.get_summary_chain(agent_name),
            retriever.get_dependency_state(),
            retriever.get_rag_context(
                agent_name,
                query=f"{agent_name}: {query_request}",
                top_k=policy.rag_top_k,
            ),
            retriever.get_workspace_snapshot(agent_name, policy.file_excerpt_chars),
            asyncio.to_thread(retriever.get_project_rules),
            retriever.get_chat_history(limit=20),
        )

        sections = {
            "User Request": compact_user_request,
            "Agent Task": compact_task,
            "Previous Context Summary Chain": self._format_summary_chain(summary_chain),
            "Relevant Knowledge": rag_context,
            "Workspace Snapshot": workspace_snapshot,
            "Dependency Signals": dependency_state,
            "Recent Chat History": self._format_chat_history(chat_history),
            "Project Rules": project_rules,
            "Context Rules": (
                "Use the provided context as grounding. Prefer generated workspace files over general knowledge. "
                "If context is missing or stale, inspect the workspace with tools before writing files."
            ),
        }

        compacted_sections, compact_record = await self.compactor.compact_sections(sections, policy)
        content = self.compactor.render_sections(compacted_sections)
        summary_id = None
        previous_summary_id = summary_chain[0]["id"] if summary_chain else None

        if compact_record and self.database and getattr(self.database, "_pool", None):
            summary_id = str(uuid.uuid4())
            try:
                await self.database.save_context_summary(
                    summary_id=summary_id,
                    project_id=project_id,
                    agent_name=agent_name,
                    summary=compact_record["summary"],
                    facts=compact_record["facts"],
                    preserved_files=files,
                    previous_summary_id=previous_summary_id,
                    source_event_count=0,
                    estimated_tokens=compact_record["after_tokens"],
                )
            except Exception as e:
                logger.warning("[ContextBuilder] Failed to persist compacted context: %s", e)
                summary_id = None

        return BuiltContext(
            content=content,
            estimated_tokens=self.estimator.estimate(content),
            compacted=compact_record is not None,
            rag_chunks=rag_count,
            file_excerpt_count=file_count,
            summary_id=summary_id,
            sources=rag_sources + files,
        )

    async def compact_and_save_events(
        self,
        project_id: str,
        agent_name: str,
        events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not events:
            return None
        policy = ContextPolicy.for_agent(agent_name)
        token_count = self.estimator.estimate(events)
        if token_count <= policy.event_budget_tokens:
            return None

        compacted = self.compactor.compact_events(events, max_tokens=policy.event_budget_tokens)
        after_tokens = self.estimator.estimate(compacted)
        summary_id = str(uuid.uuid4())

        previous_summary_id = None
        if self.database and getattr(self.database, "_pool", None):
            try:
                latest_summary = await self.database.get_latest_context_summary(project_id, agent_name)
                previous_summary_id = latest_summary.get("id") if latest_summary else None
            except Exception as e:
                logger.warning("[ContextBuilder] Failed to fetch latest summary for events: %s", e)

        if self.database and getattr(self.database, "_pool", None):
            try:
                await self.database.save_context_summary(
                    summary_id=summary_id,
                    project_id=project_id,
                    agent_name=agent_name,
                    summary=compacted["summary"],
                    facts=compacted["facts"],
                    preserved_files=[],
                    previous_summary_id=previous_summary_id,
                    source_event_count=len(events),
                    estimated_tokens=after_tokens,
                )
            except Exception as e:
                logger.warning("[ContextBuilder] Failed to persist event compaction: %s", e)
                return None

        return {
            "summary_id": summary_id,
            "previous_summary_id": previous_summary_id,
            "before_tokens": token_count,
            "after_tokens": after_tokens,
            "source_event_count": len(events),
        }

    def _format_summary_chain(self, chain: List[Dict[str, Any]]) -> str:
        if not chain:
            return ""
        parts = []
        for i, summary in enumerate(chain):
            facts = summary.get("facts")
            if isinstance(facts, str):
                try:
                    facts = json.loads(facts)
                except json.JSONDecodeError:
                    pass
            created = summary.get("created_at", "unknown")
            parts.append(
                f"[Summary {i + 1} ({created})]\n"
                f"{summary.get('summary', '')}\n"
                f"Facts: {json.dumps(facts or {}, default=str)}"
            )
        return "\n\n".join(parts)

    def _format_chat_history(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                parts.append(f"**{role.upper()}**: {content[:500]}")
        return "\n".join(parts) if parts else ""


def context_summary_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for key in ("facts", "preserved_files"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    created = result.get("created_at")
    if isinstance(created, datetime):
        result["created_at"] = created.isoformat()
    updated = result.get("updated_at")
    if isinstance(updated, datetime):
        result["updated_at"] = updated.isoformat()
    return result
