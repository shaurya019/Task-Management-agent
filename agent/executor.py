"""TOOL EXECUTOR – everything between "the LLM asked for a tool" and "here is a ToolResult".

  raw call ─► 1 lookup ─► 2 permission ─► 3 parse+validate args ─► 4 run handler w/ retries ─► ToolResult
              unknown_tool  permission_denied  invalid_json / invalid_arguments   service_unavailable …

Rule: execute() NEVER raises.  A failure is *data* the model can react to.  This is also what makes
parallel calls safe: one failing sibling can't cancel the others.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

import httpx
from pydantic import ValidationError

from . import tracing
from .api_client import ApiClient, ApiError
from .llm import ToolCall
from .results import ToolError, ToolResult
from .tools import REGISTRY, CallContext, ToolRejected, ToolSpec

log = logging.getLogger("executor")

HINTS = {
    "validation_error": "Fix the fields listed in details, then call again.",
    "unauthenticated": "Credentials are invalid. Do not retry; tell the user.",
    "invalid_token": "Credentials are invalid. Do not retry; tell the user.",
    "missing_scope": "You are not permitted to do this. Do not retry; tell the user what is not allowed.",
    "forbidden_owner_filter": "You may only list your own tasks. Omit owner_id.",
    "task_not_found": "Verify the id with list_tasks (ids look like t_xxxxxxxxxxxx). Do not invent ids.",
    "user_not_found": "Ask the user to double-check the email address.",
    "version_conflict": "The task changed since you read it. Call get_task for the latest state, re-apply "
                        "the change, and pass the new version as expected_version.",
    "quota_exceeded": "Ask the user which tasks to delete first.",
    "idempotency_key_reuse": "Internal error: do not retry; tell the user.",
}
RETRYABLE_AFTER_HINT = {"validation_error", "version_conflict", "confirmation_required"}


@dataclass
class RetryPolicy:
    """Exponential backoff with jitter for TRANSIENT failures only."""
    max_attempts: int = 3
    base_delay: float = 0.3
    max_delay: float = 3.0
    jitter: float = 0.25
    statuses: frozenset[int] = frozenset({429, 502, 503, 504})

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        d = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        d += random.uniform(0, d * self.jitter)
        return max(d, min(retry_after, self.max_delay)) if retry_after else d


def _err(spec_name: str, call_id: str, code: str, message: str, *, hint: str | None = None,
         retryable: bool = False, details: list | None = None, mutating: bool = False,
         attempts: int = 1, ms: int = 0, request_id: str | None = None) -> ToolResult:
    return ToolResult(tool=spec_name, call_id=call_id, ok=False, mutating=mutating, attempts=attempts,
                      duration_ms=ms, request_id=request_id,
                      error=ToolError(code=code, message=message, hint=hint, retryable=retryable,
                                      details=details or []))


class ToolExecutor:
    def __init__(self, api: ApiClient, granted_scopes: Iterable[str],
                 registry: dict[str, ToolSpec] | None = None, retry: RetryPolicy | None = None,
                 max_parallel: int = 5, tool_timeout: float = 20.0,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.api = api
        self.scopes = frozenset(granted_scopes)
        self.registry = registry or REGISTRY
        self.retry = retry or RetryPolicy()
        self.tool_timeout = tool_timeout
        self._sem = asyncio.Semaphore(max_parallel)      # cap concurrency so we never DoS our own API
        self._sleep = sleep

    # ── planning: which calls may run together? ────────────────────────
    def _is_parallel_safe(self, call: ToolCall) -> bool:
        spec = self.registry.get(call.name)
        return spec.parallel_safe if spec else True      # unknown tool = instant error, harmless

    def plan_batches(self, calls: list[ToolCall]) -> list[list[ToolCall]]:
        """Consecutive parallel-safe calls form ONE concurrent batch.
        A non-safe call (update/delete) is a BARRIER: it runs alone, in order.
        e.g. [get, get, list, update, get] → [[get,get,list], [update], [get]]"""
        batches: list[list[ToolCall]] = []
        for c in calls:
            if batches and self._is_parallel_safe(c) and self._is_parallel_safe(batches[-1][-1]):
                batches[-1].append(c)
            else:
                batches.append([c])
        return batches

    async def execute_batch(self, calls: list[ToolCall], run_id: str) -> list[ToolResult]:
        """Results come back in the SAME ORDER as `calls` (the API requires one tool message per id)."""
        results: list[ToolResult] = []
        for batch in self.plan_batches(calls):
            if len(batch) == 1:
                results.append(await self.execute(batch[0], run_id))
            else:                                                     # PARALLEL fan-out
                results.extend(await asyncio.gather(*(self._bounded(c, run_id) for c in batch)))
        return results

    async def _bounded(self, call: ToolCall, run_id: str) -> ToolResult:
        async with self._sem:
            return await self.execute(call, run_id)

    # ── one tool call ──────────────────────────────────────────────────
    @tracing.observe(name="tool.execute", as_type="tool", capture_input=False, capture_output=False)
    async def execute(self, call: ToolCall, run_id: str) -> ToolResult:
        t0 = time.perf_counter()
        result = await self._execute(call, run_id)
        result.duration_ms = int((time.perf_counter() - t0) * 1000)
        tracing.span_update(
            name=f"tool.{call.name}", input=_safe_json(call.arguments),
            output=_safe_json(result.to_llm(2000)),
            metadata={"call_id": call.id, "attempts": str(result.attempts), "ok": str(result.ok),
                      "cached": str(result.cached), "request_id": result.request_id or ""},
            **({} if result.ok else {"level": "WARNING",
                                    "status_message": f"{result.error.code}: {result.error.message}"}))
        return result

    async def _execute(self, call: ToolCall, run_id: str) -> ToolResult:
        # 1 ── lookup
        spec = self.registry.get(call.name)
        if spec is None:
            return _err(call.name, call.id, "unknown_tool", f"No tool named '{call.name}'.",
                        hint=f"Available tools: {', '.join(s.name for s in self.available())}")
        # 2 ── TOOL PERMISSION (checked before any network I/O)
        if spec.scope not in self.scopes:
            return _err(spec.name, call.id, "permission_denied",
                        f"Your session may not use '{spec.name}' (needs scope {spec.scope}).",
                        hint="Do not retry. Tell the user this action is not permitted for their account.",
                        mutating=not spec.read_only)
        # 3 ── parse + validate LLM-produced arguments
        try:
            raw = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as e:
            return _err(spec.name, call.id, "invalid_json", f"Arguments are not valid JSON: {e.msg}",
                        hint="Send a single JSON object.", retryable=True, mutating=not spec.read_only)
        try:
            args = spec.args_model.model_validate(raw)
        except ValidationError as e:
            details = [{"field": ".".join(map(str, x["loc"])), "message": x["msg"]} for x in e.errors()]
            return _err(spec.name, call.id, "invalid_arguments", "Arguments failed validation.",
                        hint="Correct the listed fields and call again.", retryable=True, details=details,
                        mutating=not spec.read_only)
        # 4 ── run with retries
        ctx = CallContext(call_id=call.id, request_id=call.id,
                          idempotency_key=f"{run_id}:{call.id}")   # same key for every retry of THIS call
        return await self._run_with_retries(spec, args, ctx)

    def available(self) -> list[ToolSpec]:
        return [s for s in self.registry.values() if s.scope in self.scopes]

    async def _run_with_retries(self, spec: ToolSpec, args, ctx: CallContext) -> ToolResult:
        mutating, attempts = not spec.read_only, 0
        common = dict(mutating=mutating, request_id=ctx.request_id)
        while True:
            attempts += 1
            try:
                data = await asyncio.wait_for(spec.handler(self.api, args, ctx), self.tool_timeout)
                return ToolResult(tool=spec.name, call_id=ctx.call_id, ok=True, data=data,
                                  attempts=attempts, **common)
            except ToolRejected as e:                                   # local, deterministic → no retry
                return _err(spec.name, ctx.call_id, e.code, e.message, hint=e.hint, retryable=e.retryable,
                            attempts=attempts, **common)
            except ApiError as e:
                if e.status in self.retry.statuses and attempts < self.retry.max_attempts:
                    await self._backoff(spec, attempts, f"HTTP {e.status}", e.retry_after)
                    continue
                if e.status in self.retry.statuses:
                    return self._unavailable(spec, ctx, attempts, f"HTTP {e.status} {e.code}")
                return _err(spec.name, ctx.call_id, e.code, e.message,
                            hint=HINTS.get(e.code, "Do not retry blindly; report the problem to the user."),
                            retryable=e.code in RETRYABLE_AFTER_HINT, details=e.details,
                            attempts=attempts, **common)
            except (httpx.TransportError, asyncio.TimeoutError) as e:   # network blip / timeout
                if attempts < self.retry.max_attempts:
                    await self._backoff(spec, attempts, type(e).__name__)
                    continue
                return self._unavailable(spec, ctx, attempts, type(e).__name__)
            except ValidationError as e:                                # server broke its own contract
                return _err(spec.name, ctx.call_id, "bad_response",
                            "The API returned data that does not match the expected schema.",
                            hint="Do not retry; report an internal error.", attempts=attempts,
                            details=[{"field": ".".join(map(str, x["loc"])), "message": x["msg"]}
                                     for x in e.errors()[:5]], **common)
            except Exception as e:                                      # bug in OUR code – contain it
                log.exception("tool %s crashed", spec.name)
                return _err(spec.name, ctx.call_id, "internal_error", f"{type(e).__name__}: {e}",
                            hint="Do not retry; report an internal error.", attempts=attempts, **common)

    def _unavailable(self, spec, ctx, attempts, why) -> ToolResult:
        return _err(spec.name, ctx.call_id, "service_unavailable",
                    f"Backend unavailable after {attempts} attempts ({why}).",
                    hint="Do not call this tool again now. Tell the user what succeeded so far and that "
                         "this step could not be completed.", retryable=False, mutating=not spec.read_only,
                    attempts=attempts, request_id=ctx.request_id)

    async def _backoff(self, spec: ToolSpec, attempt: int, why: str, retry_after: float | None = None):
        delay = self.retry.delay(attempt, retry_after)
        log.warning("retrying %s (attempt %d) after %s in %.2fs", spec.name, attempt, why, delay)
        await self._sleep(delay)


def _safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return s
