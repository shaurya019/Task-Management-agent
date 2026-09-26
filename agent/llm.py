"""LLM adapter.  The agent depends on the tiny `LLM` protocol, never on the OpenAI SDK directly,
which is what lets the tests drive the whole agent with a scripted FakeLLM (no API key)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import tracing


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str                       # raw JSON string exactly as the model produced it


@dataclass
class LLMTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": tc.id, "type": "function",
                                  "function": {"name": tc.name, "arguments": tc.arguments}}
                                 for tc in self.tool_calls]
        return msg


class LLM(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   tool_choice: str = "auto") -> LLMTurn: ...


class OpenAILLM:
    """Chat Completions with tool calling.

    `parallel_tool_calls=True` lets the model return SEVERAL tool_calls in one assistant message
    when it judges them independent – that is "LLM-generated parallel tool calling".
    """

    def __init__(self, model: str, api_key: str | None = None, parallel_tool_calls: bool = True):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set (put it in .env)")
        if tracing.ENABLED:
            from langfuse.openai import AsyncOpenAI       # drop-in wrapper: every call → a Langfuse generation
        else:
            from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)        # SDK already retries 429/5xx twice with backoff
        self.model = model
        self.parallel = parallel_tool_calls

    async def chat(self, messages, tools=None, tool_choice="auto") -> LLMTurn:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice, parallel_tool_calls=self.parallel)
        if tracing.ENABLED:
            kwargs["name"] = "agent-llm-call"             # Langfuse-only kwarg (label of the generation)
        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "{}")
                 for tc in (msg.tool_calls or []) if tc.type == "function"]
        usage = {}
        if resp.usage:
            usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
        return LLMTurn(content=msg.content, tool_calls=calls, usage=usage)
