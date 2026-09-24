"""TOOL-RESULT FORMATTING – the contract between your code and the LLM.

The model only ever sees a string.  A good tool result is:
  • uniform     – always {"ok": bool, "tool": ..., "data"|"error": ...}
  • compact     – null fields dropped, long lists truncated (tokens cost money + attention)
  • actionable  – errors carry `code`, `retryable` and a `hint` saying what to do NEXT
  • honest      – failures are returned as data, never raised into the LLM loop
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False            # "would the SAME call plausibly succeed after applying `hint`?"
    hint: str | None = None
    details: list[dict[str, Any]] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool: str
    call_id: str
    ok: bool
    data: Any = None
    error: ToolError | None = None
    mutating: bool = False
    attempts: int = 1
    duration_ms: int = 0
    cached: bool = False
    note: str | None = None
    request_id: str | None = None

    # ── formatting ─────────────────────────────────────────────────────
    def to_llm(self, max_chars: int = 6000) -> str:
        payload: dict[str, Any] = {"ok": self.ok, "tool": self.tool}
        if self.ok:
            payload["data"] = _compact(self.data)
        else:
            payload["error"] = self.error.model_dump(exclude_none=True, exclude_defaults=False) if self.error else {}
            if not payload["error"].get("details"):
                payload["error"].pop("details", None)
        if self.note:
            payload["note"] = self.note
        if self.attempts > 1:
            payload["attempts"] = self.attempts
        return _fit(payload, max_chars)


def _compact(value: Any) -> Any:
    """Drop None / empty values recursively and boilerplate timestamps to save tokens."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "created_at":
                continue
            cv = _compact(v)
            if cv is None or cv == [] or cv == {}:
                continue
            out[k] = cv
        return out
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str, ensure_ascii=False)


def _fit(payload: dict, max_chars: int) -> str:
    s = _dumps(payload)
    if len(s) <= max_chars:
        return s
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):     # shrink lists first
        items, total = data["items"], len(data["items"])
        while items and len(_dumps(payload)) > max_chars:
            items.pop()
        data["truncated"] = True
        data["shown"] = len(items)
        data["omitted"] = total - len(items)
        data["hint"] = "Result truncated. Narrow the filters or use offset/limit to page."
        return _dumps(payload)
    if isinstance(data, dict):                                              # then long strings
        for k, v in list(data.items()):
            if isinstance(v, str) and len(v) > 300:
                data[k] = v[:300] + "…[truncated]"
    s = _dumps(payload)
    return s if len(s) <= max_chars else s[: max_chars - 40] + '…[truncated]"}'
