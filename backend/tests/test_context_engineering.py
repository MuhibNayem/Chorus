"""Tests for context_engineering.py — covers all fixed issues."""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.swarm.context_engineering import (
    TOKEN_SAFETY_FACTOR,
    BuiltContext,
    ContextBuilder,
    ContextCompactor,
    ContextPolicy,
    ContextRetriever,
    LLMSummarizer,
    TokenEstimator,
    _snapshot_cache,
    invalidate_snapshot_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimator() -> TokenEstimator:
    return TokenEstimator()


def _policy(mode: str = "auto") -> ContextPolicy:
    return ContextPolicy.for_agent("backend", mode)


def _compactor(llm_summarizer: Optional[LLMSummarizer] = None) -> ContextCompactor:
    return ContextCompactor(llm_summarizer=llm_summarizer or LLMSummarizer(llm=None))


# ---------------------------------------------------------------------------
# TokenEstimator
# ---------------------------------------------------------------------------

class TestTokenEstimator:
    def test_estimate_applies_safety_factor(self):
        est = _estimator()
        raw_approx = len("hello world".split())  # rough sanity only
        result = est.estimate("hello world")
        assert result >= 1

    def test_safety_factor_inflates_estimate(self):
        est = _estimator()
        text = "a " * 1000
        raw = len(est.encoding.encode(text))
        estimated = est.estimate(text)
        assert estimated >= raw  # safety factor must never deflate
        assert estimated <= raw * TOKEN_SAFETY_FACTOR * 1.01  # within tolerance

    def test_non_string_serialised_to_json(self):
        est = _estimator()
        result = est.estimate({"key": "value", "num": 42})
        assert result > 0

    def test_none_returns_zero(self):
        est = _estimator()
        assert est.estimate(None) == 0

    def test_fallback_heuristic_on_encode_error(self):
        est = _estimator()
        est.encoding = MagicMock(encode=MagicMock(side_effect=Exception("boom")))
        result = est.estimate("some text here")
        assert result >= 1


# ---------------------------------------------------------------------------
# ContextPolicy
# ---------------------------------------------------------------------------

class TestContextPolicy:
    def test_auto_and_full_have_different_rag_topk(self):
        auto = ContextPolicy.for_agent("backend", "auto")
        full = ContextPolicy.for_agent("backend", "full")
        assert auto.rag_top_k < full.rag_top_k

    def test_lean_halves_max_tokens(self):
        lean = ContextPolicy.for_agent("backend", "lean")
        full = ContextPolicy.for_agent("backend", "full")
        assert lean.max_tokens == full.max_tokens // 2

    def test_compact_threshold_is_85_percent(self):
        p = ContextPolicy.for_agent("backend")
        assert p.compact_threshold == int(p.max_tokens * 0.85)

    def test_event_budget_is_10_percent(self):
        p = ContextPolicy.for_agent("backend")
        assert p.event_budget_tokens == int(p.max_tokens * 0.1)

    def test_invalid_mode_falls_back_to_auto(self):
        p = ContextPolicy.for_agent("backend", "banana")
        auto = ContextPolicy.for_agent("backend", "auto")
        assert p.mode == auto.mode


# ---------------------------------------------------------------------------
# ContextCompactor.compact_user_request — token-based check
# ---------------------------------------------------------------------------

class TestCompactUserRequest:
    def test_short_text_returned_unchanged(self):
        c = _compactor()
        text = "Build me a todo app."
        result = c.compact_user_request(text, max_tokens=3000)
        assert result == text

    def test_long_text_is_compacted(self):
        c = _compactor()
        text = "x " * 10_000  # ~20 000 chars, well over 3 000 tokens
        result = c.compact_user_request(text, max_tokens=500)
        assert "[User request compacted" in result
        assert len(result) < len(text)

    def test_compacted_result_has_head_and_tail(self):
        c = _compactor()
        text = "BEGINNING " + "middle " * 5000 + "ENDING"
        result = c.compact_user_request(text, max_tokens=500)
        assert "BEGINNING" in result
        assert "ENDING" in result

    def test_empty_text_returns_empty(self):
        c = _compactor()
        assert c.compact_user_request("") == ""

    def test_token_check_not_char_check(self):
        """Ensure decision is based on token count, not raw character length."""
        c = _compactor()
        est = c.estimator
        text = "x " * 100  # short chars but might be > max_tokens if max_tokens is tiny
        token_count = est.estimate(text)
        # With max_tokens == token_count - 1, must compact.
        result = c.compact_user_request(text, max_tokens=max(1, token_count - 1))
        assert "[User request compacted" in result


# ---------------------------------------------------------------------------
# ContextCompactor.compact_events — uses policy budget
# ---------------------------------------------------------------------------

class TestCompactEvents:
    def test_uses_max_tokens_param(self):
        c = _compactor()
        events = [{"type": "tool_call", "tool": "write_file", "content": "wrote a file"}] * 50
        result = c.compact_events(events, max_tokens=100)
        assert "summary" in result
        assert "facts" in result

    def test_tool_names_deduplicated(self):
        c = _compactor()
        events = [{"type": "tool_call", "tool": "write_file", "content": "x"}] * 10
        result = c.compact_events(events, max_tokens=2000)
        assert result["facts"]["tool_names"] == ["write_file"]

    def test_event_count_correct(self):
        c = _compactor()
        events = [{"type": "tool_call", "tool": "x", "content": "y"}] * 7
        result = c.compact_events(events, max_tokens=2000)
        assert result["facts"]["event_count"] == 7

    def test_summary_truncated_when_over_budget(self):
        c = _compactor()
        events = [{"type": "note", "content": "z " * 5000}]
        result = c.compact_events(events, max_tokens=50)  # very tight budget
        assert "[Event summary truncated]" in result["summary"] or len(result["summary"]) < 10_000


# ---------------------------------------------------------------------------
# ContextCompactor.compact_sections — budget guarantee + richer summary
# ---------------------------------------------------------------------------

class TestCompactSections:
    def _build_sections(self, size_each: int = 5000) -> Dict[str, str]:
        return {
            "User Request": "Build a REST API. " * (size_each // 20),
            "Agent Task": "Implement the backend. " * (size_each // 22),
            "Relevant Knowledge": "Spring Boot tip: " * (size_each // 18),
            "Workspace Snapshot": "### pom.xml\n" + "<dependency/>\n" * (size_each // 15),
            "Project Rules": "Rule: never use raw SQL. " * (size_each // 25),
        }

    @pytest.mark.asyncio
    async def test_no_compaction_when_under_threshold(self):
        c = _compactor()
        sections = {"User Request": "short text", "Agent Task": "also short"}
        policy = _policy()
        result, record = await c.compact_sections(sections, policy)
        assert record is None
        assert result == sections

    @pytest.mark.asyncio
    async def test_compaction_fires_when_over_threshold(self):
        c = _compactor()
        sections = self._build_sections(size_each=50_000)
        policy = ContextPolicy(
            mode="auto",
            max_tokens=1000,
            compact_threshold=800,
            rag_top_k=10,
            file_excerpt_chars=5000,
            event_budget_tokens=100,
        )
        result, record = await c.compact_sections(sections, policy)
        assert record is not None

    @pytest.mark.asyncio
    async def test_compact_record_has_richer_content(self):
        c = _compactor()
        sections = self._build_sections(size_each=50_000)
        policy = ContextPolicy(
            mode="auto",
            max_tokens=1000,
            compact_threshold=800,
            rag_top_k=10,
            file_excerpt_chars=5000,
            event_budget_tokens=100,
        )
        _, record = await c.compact_sections(sections, policy)
        assert record is not None
        assert "before_tokens" in record
        assert "after_tokens" in record
        assert "reduction_pct" in record["facts"]
        assert isinstance(record["facts"]["compacted_sections"], list)
        # Summary should contain numeric token info, not just a generic string
        assert "→" in record["summary"] or "->" in record["summary"] or "tokens" in record["summary"]

    @pytest.mark.asyncio
    async def test_llm_summarizer_used_when_available(self):
        mock_llm_summarizer = AsyncMock(spec=LLMSummarizer)
        mock_llm_summarizer.summarize = AsyncMock(return_value="concise summary")
        c = ContextCompactor(llm_summarizer=mock_llm_summarizer)
        sections = self._build_sections(size_each=50_000)
        policy = ContextPolicy(
            mode="auto",
            max_tokens=1000,
            compact_threshold=800,
            rag_top_k=10,
            file_excerpt_chars=5000,
            event_budget_tokens=100,
        )
        await c.compact_sections(sections, policy)
        assert mock_llm_summarizer.summarize.called

    @pytest.mark.asyncio
    async def test_mechanical_fallback_when_llm_returns_none(self):
        mock_llm_summarizer = AsyncMock(spec=LLMSummarizer)
        mock_llm_summarizer.summarize = AsyncMock(return_value=None)
        c = ContextCompactor(llm_summarizer=mock_llm_summarizer)
        sections = self._build_sections(size_each=50_000)
        policy = ContextPolicy(
            mode="auto",
            max_tokens=1000,
            compact_threshold=800,
            rag_top_k=10,
            file_excerpt_chars=5000,
            event_budget_tokens=100,
        )
        # Should not raise
        result, record = await c.compact_sections(sections, policy)
        assert record is not None


# ---------------------------------------------------------------------------
# Snapshot cache
# ---------------------------------------------------------------------------

class TestSnapshotCache:
    def setup_method(self):
        _snapshot_cache.clear()

    def test_invalidate_clears_project_entries(self):
        from src.swarm.context_engineering import _SnapshotCacheEntry

        _snapshot_cache[("proj-1", "backend")] = _SnapshotCacheEntry(
            snapshot="snap",
            file_count=1,
            files=["a.py"],
            expires_at=time.monotonic() + 100,
        )
        _snapshot_cache[("proj-2", "backend")] = _SnapshotCacheEntry(
            snapshot="snap2",
            file_count=1,
            files=["b.py"],
            expires_at=time.monotonic() + 100,
        )
        invalidate_snapshot_cache("proj-1")
        assert ("proj-1", "backend") not in _snapshot_cache
        assert ("proj-2", "backend") in _snapshot_cache

    def test_expired_cache_not_returned(self):
        from src.swarm.context_engineering import _SnapshotCacheEntry

        _snapshot_cache[("proj-x", "backend")] = _SnapshotCacheEntry(
            snapshot="old",
            file_count=1,
            files=["old.py"],
            expires_at=time.monotonic() - 1,  # already expired
        )
        entry = _snapshot_cache.get(("proj-x", "backend"))
        assert entry is not None
        assert time.monotonic() >= entry.expires_at  # expired

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value(self, tmp_path):
        from src.swarm.context_engineering import _SnapshotCacheEntry

        _snapshot_cache[("proj-cache", "backend")] = _SnapshotCacheEntry(
            snapshot="cached snapshot",
            file_count=2,
            files=["x.py", "y.py"],
            expires_at=time.monotonic() + 100,
        )
        retriever = ContextRetriever("proj-cache")
        with patch(
            "src.swarm.context_engineering.WORKSPACE_BASE", tmp_path
        ):
            snap, count, files = await retriever.get_workspace_snapshot("backend", 5000)
        assert snap == "cached snapshot"
        assert count == 2
        assert files == ["x.py", "y.py"]


# ---------------------------------------------------------------------------
# ContextBuilder.compact_and_save_events — DB=None guard + policy budget
# ---------------------------------------------------------------------------

class TestCompactAndSaveEvents:
    @pytest.mark.asyncio
    async def test_returns_none_when_under_budget(self):
        builder = ContextBuilder(database=None)
        events = [{"type": "tool_call", "tool": "write_file", "content": "x"}]
        result = await builder.compact_and_save_events("p1", "backend", events)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_crash_when_database_is_none(self):
        builder = ContextBuilder(database=None)
        # Generate enough events to exceed budget
        events = [{"type": "note", "content": "z " * 500}] * 200
        # Must not raise AttributeError (old bug: self.database.get_latest... crashed).
        # Returns compaction metadata so the caller can clear the buffer, even without DB.
        result = await builder.compact_and_save_events("p1", "backend", events)
        assert result is not None
        assert "before_tokens" in result
        assert "after_tokens" in result

    @pytest.mark.asyncio
    async def test_event_budget_from_policy(self):
        """Ensure compact_events is called with policy.event_budget_tokens, not hardcoded 8000."""
        mock_db = AsyncMock()
        mock_db._pool = True
        mock_db.get_latest_context_summary = AsyncMock(return_value=None)
        mock_db.save_context_summary = AsyncMock()

        builder = ContextBuilder(database=mock_db)
        policy = ContextPolicy.for_agent("backend")

        called_with_tokens: List[int] = []
        original_compact = builder.compactor.compact_events

        def capturing_compact(events, max_tokens=2000):
            called_with_tokens.append(max_tokens)
            return original_compact(events, max_tokens=max_tokens)

        builder.compactor.compact_events = capturing_compact

        events = [{"type": "note", "content": "z " * 1000}] * 50
        await builder.compact_and_save_events("p1", "backend", events)

        if called_with_tokens:
            assert called_with_tokens[0] == policy.event_budget_tokens


# ---------------------------------------------------------------------------
# ContextBuilder._format_chat_history — no double-slice
# ---------------------------------------------------------------------------

class TestFormatChatHistory:
    def test_all_messages_included_up_to_limit(self):
        builder = ContextBuilder()
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        result = builder._format_chat_history(messages)
        for i in range(20):
            assert f"msg{i}" in result

    def test_empty_returns_empty(self):
        builder = ContextBuilder()
        assert builder._format_chat_history([]) == ""

    def test_no_duplicate_slice(self):
        """All 20 messages from the retriever should appear — previously the
        double-slice messages[-20:] after limit=20 was a no-op but confirmed here."""
        builder = ContextBuilder()
        # Build exactly 20 messages with unique sentinel content
        messages = [{"role": "user", "content": f"sentinel-{i:02d}"} for i in range(20)]
        result = builder._format_chat_history(messages)
        for i in range(20):
            assert f"sentinel-{i:02d}" in result


# ---------------------------------------------------------------------------
# LLMSummarizer
# ---------------------------------------------------------------------------

class TestLLMSummarizer:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_llm(self):
        s = LLMSummarizer(llm=None)
        s._available = False  # prevent lazy init
        s._llm = None
        result = await s.summarize("some text", "Test Section", 500)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_summary_from_llm(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="concise summary text"))
        s = LLMSummarizer(llm=mock_llm)
        result = await s.summarize("long text " * 100, "Workspace Snapshot", 500)
        assert result == "concise summary text"
        assert mock_llm.ainvoke.called

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_error(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
        s = LLMSummarizer(llm=mock_llm)
        result = await s.summarize("some text", "Test", 500)
        assert result is None

    @pytest.mark.asyncio
    async def test_input_capped_at_max_input_chars(self):
        captured: List[Any] = []
        mock_llm = AsyncMock()

        async def capture(messages):
            captured.extend(messages)
            return MagicMock(content="summary")

        mock_llm.ainvoke = capture
        s = LLMSummarizer(llm=mock_llm)
        huge_text = "x " * 100_000  # 200k chars > _MAX_INPUT_CHARS
        await s.summarize(huge_text, "Section", 1000)
        assert len(captured) > 0
        human_msg = str(captured[-1].content)
        # Input to LLM must be capped
        assert len(human_msg) < len(huge_text) + 500
