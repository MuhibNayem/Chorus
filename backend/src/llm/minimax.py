import os
import asyncio
import time
import logging
import httpx
from typing import Optional, List, Dict, Any, AsyncIterator, Iterator
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("minimax-llm")

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimax.io/v1"

AGENT_MAX_TOKENS = {
    "rootdep": 32768,
    "backend": 32768,
    "frontend": 32768,
    "devops": 16384,
    "packager": 16384,
}

# Per-agent temperature: lower for architects/planners (reduce hallucination),
# moderate for creative coding agents.
AGENT_TEMPERATURE = {
    "rootdep": 0.3,
    "backend": 0.7,
    "frontend": 0.7,
    "devops": 0.7,
    "packager": 0.5,
}

_retry_kwargs = dict(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))


class _BoundMiniMaxLLM:
    """Proxy that applies retry logic to a bound LangChain runnable.

    LangChain agent creation calls ``bind_tools()`` on the model and then
    invokes ``ainvoke()`` / ``invoke()`` on the *bound* object.  If we
    return the raw ``ChatOpenAI`` binding, those calls bypass the retry
    decorators on ``MiniMaxLLM``.  This wrapper intercepts the critical
    call paths and retries them on transient network errors.
    """

    def __init__(self, bound_obj: Any):
        self._bound_obj = bound_obj

    @retry(**_retry_kwargs)
    async def ainvoke(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Any:
        return await self._bound_obj.ainvoke(input, config=config, **kwargs)

    @retry(**_retry_kwargs)
    def invoke(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Any:
        return self._bound_obj.invoke(input, config=config, **kwargs)

    async def astream(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> AsyncIterator[Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                async for chunk in self._bound_obj.astream(input, config=config, **kwargs):
                    yield chunk
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"[MiniMax] astream attempt {attempt} failed: {e}")
                if attempt >= 3:
                    raise last_exc  # type: ignore[misc]
                await asyncio.sleep(2 ** attempt)

    def stream(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Iterator[Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                for chunk in self._bound_obj.stream(input, config=config, **kwargs):
                    yield chunk
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"[MiniMax] stream attempt {attempt} failed: {e}")
                if attempt >= 3:
                    raise last_exc  # type: ignore[misc]
                time.sleep(2 ** attempt)

    async def astream_events(
        self,
        input: Any,
        config: Optional[Any] = None,
        *,
        version: str = "v2",
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                async for event in self._bound_obj.astream_events(
                    input, config=config, version=version, **kwargs
                ):
                    yield event
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"[MiniMax] astream_events attempt {attempt} failed: {e}")
                if attempt >= 3:
                    raise last_exc  # type: ignore[misc]
                await asyncio.sleep(2 ** attempt)

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "_BoundMiniMaxLLM":
        return _BoundMiniMaxLLM(self._bound_obj.bind_tools(tools, **kwargs))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_BoundMiniMaxLLM":
        return _BoundMiniMaxLLM(self._bound_obj.with_structured_output(schema, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bound_obj, name)


class MiniMaxLLM:
    def __init__(
        self,
        model: str = "MiniMax-M2.7",
        api_key: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        timeout: int = 3600,
    ):
        self.model = model
        self.api_key = api_key or MINIMAX_API_KEY
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY must be set")

        custom_timeout = httpx.Timeout(
            connect=15.0,
            read=float(self.timeout),
            write=15.0,
            pool=15.0
        )

        self.llm = ChatOpenAI(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=MINIMAX_BASE_URL,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=custom_timeout,
            max_retries=0,
            stream_chunk_timeout=None,
        )

    @property
    def _client_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def ainvoke(self, messages: List[BaseMessage]) -> AIMessage:
        logger.info(f"[MiniMax] ainvoke request: {len(messages)} messages, params={self._client_params}")
        try:
            result = await self.llm.ainvoke(messages)
            logger.info(f"[MiniMax] ainvoke response: type={type(result).__name__}, content_length={len(str(result))}")
            return result
        except Exception as e:
            logger.error(f"[MiniMax] ainvoke error: {type(e).__name__}: {e}, args={e.args if e.args else 'none'}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def invoke(self, messages: List[BaseMessage]) -> AIMessage:
        logger.info(f"[MiniMax] invoke request: {len(messages)} messages, params={self._client_params}")
        try:
            result = self.llm.invoke(messages)
            logger.info(f"[MiniMax] invoke response: type={type(result).__name__}, content_length={len(str(result))}")
            return result
        except Exception as e:
            logger.error(f"[MiniMax] invoke error: {type(e).__name__}: {e}, args={e.args if e.args else 'none'}")
            raise

    def stream(self, messages: List[BaseMessage]):
        logger.info(f"[MiniMax] stream request: {len(messages)} messages, params={self._client_params}")
        try:
            stream_result = self.llm.stream(messages)
            logger.info(f"[MiniMax] stream started")
            return stream_result
        except Exception as e:
            logger.error(f"[MiniMax] stream error: {type(e).__name__}: {e}, args={e.args if e.args else 'none'}")
            raise

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> _BoundMiniMaxLLM:
        return _BoundMiniMaxLLM(self.llm.bind_tools(tools, **kwargs))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _BoundMiniMaxLLM:
        return _BoundMiniMaxLLM(self.llm.with_structured_output(schema, **kwargs))


class MiniMaxReActLLM(MiniMaxLLM):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tools = []

    def with_tools(self, tools: List[Any]):
        self.tools = tools
        return self


def get_llm(provider: str = "minimax", agent_name: Optional[str] = None) -> MiniMaxLLM:
    if provider != "minimax":
        raise ValueError(f"Unknown provider: {provider}")
    max_tokens = AGENT_MAX_TOKENS.get(agent_name, 8192) if agent_name else 8192
    temperature = AGENT_TEMPERATURE.get(agent_name, 0.7)
    return MiniMaxLLM(model="MiniMax-M2.7", temperature=temperature, max_tokens=max_tokens)


def create_minimax_client(agent_name: Optional[str] = None) -> MiniMaxLLM:
    max_tokens = AGENT_MAX_TOKENS.get(agent_name, 8192) if agent_name else 8192
    temperature = AGENT_TEMPERATURE.get(agent_name, 0.7)
    return MiniMaxLLM(
        model="MiniMax-M2.7",
        temperature=temperature,
        max_tokens=max_tokens,
    )
