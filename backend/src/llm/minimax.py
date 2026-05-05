import os
from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from tenacity import retry, stop_after_attempt, wait_exponential

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimax.io/v1"


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
            stream_chunk_timeout=None,  # Disable chunk timeout — reasoning models pause between tokens
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def ainvoke(self, messages: List[BaseMessage]) -> AIMessage:
        return await self.llm.ainvoke(messages)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def invoke(self, messages: List[BaseMessage]) -> AIMessage:
        return self.llm.invoke(messages)

    def stream(self, messages: List[BaseMessage]):
        return self.llm.stream(messages)

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


def get_llm(provider: str = "minimax") -> MiniMaxLLM:
    return MiniMaxLLM()


def create_minimax_client() -> MiniMaxLLM:
    return MiniMaxLLM(
        model="MiniMax-M2.7",
        temperature=1.0,
        max_tokens=8192,
    )
