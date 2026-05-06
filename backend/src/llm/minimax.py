import os
import logging
from typing import Optional, List, Dict, Any
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


class MiniMaxLLM:
    def __init__(
        self,
        model: str = "MiniMax-M2.7",
        api_key: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: int = 8192,
        timeout: int = 300,
    ):
        self.model = model
        self.api_key = api_key or MINIMAX_API_KEY
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY must be set")

        self.llm = ChatOpenAI(
            model=self.model,
            openai_api_key=self.api_key,
            openai_api_base=MINIMAX_BASE_URL,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
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

    def bind_tools(self, tools: List[Any], **kwargs):
        return self.llm.bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any):
        return self.llm.with_structured_output(schema)


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
    return MiniMaxLLM(max_tokens=max_tokens)


def create_minimax_client(agent_name: Optional[str] = None) -> MiniMaxLLM:
    max_tokens = AGENT_MAX_TOKENS.get(agent_name, 8192) if agent_name else 8192
    return MiniMaxLLM(
        model="MiniMax-M2.7",
        temperature=1.0,
        max_tokens=max_tokens,
    )
