"""THE AGENT LOOP.

  User ─► Agent ─► LLM ──(tool_calls)──► Executor ─► Tool ─► FastAPI ─► DB
             ▲                                                          │
             └──────────── ToolResult (JSON string) ◄───────────────────┘
  and around again until the LLM answers in plain text.

Safety rails (each one is a test in tests/test_agent.py):
    max_iterations      hard cap on LLM round-trips
    max_tool_calls      hard cap on total tool executions
    duplicate guard     identical call (same args, same world state) is not executed again
    failure guard       N consecutive rounds where every tool failed → stop
    graceful stop       on ANY stop reason the LLM is asked (tools disabled) to report honestly what was
                        done / not done  →  status "partial" instead of a crash or a silent loop
"""
from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal

from . import tracing
from .executor import ToolExecutor
from .llm import LLM, LLMTurn, ToolCall
from .results import ToolError, ToolResult
from .run_store import NullRunStore, RunStore
from .state import RunState, StepRecord


@dataclass
class AgentConfig:
    max_iterations: int = 8            # LLM round-trips per user message
    max_tool_calls: int = 20           # total tool executions per user message
    max_duplicate_calls: int = 2       # repeated identical calls tolerated before we declare a loop
    max_failed_rounds: int = 3         # consecutive all-failed rounds tolerated
    max_result_chars: int = 6000       # per tool message


@dataclass
class AgentResult:
    status: Literal["completed", "partial", "failed"]
    answer: str
    stop_reason: str | None
    run_id: str
    iterations: int
    tool_calls: int
    steps: list[StepRecord]
    changes: list[str]
    usage: dict[str, int] = field(default_factory=dict)
    trace_url: str | None = None


SYSTEM_PROMPT = """You are a task-management assistant. You act ONLY through the provided tools, on behalf of
{name} <{email}> (role: {role}). Today is {today}.

TOOL-USE RULES
1. Independent lookups -> call the tools TOGETHER in one turn (parallel). Example: fetching 3 known task ids.
2. Dependent steps -> ONE step at a time, because you need the previous output. Example: find_user -> list_tasks
   (needs the user id) -> get_task/update_task (needs a task id). Never invent ids, versions or emails.
3. Read the JSON tool results carefully. `ok:false` means the action did NOT happen. Follow `error.hint`.
4. Never repeat a call that already failed with the same arguments. Never repeat a write listed under
   WORKING MEMORY. If `version_conflict`: get_task again, re-apply, pass the new expected_version.
5. delete_task is destructive: first ask the user to confirm; only then call it with confirm=true.
6. If a tool says you lack permission, tell the user plainly; do not look for a workaround.
7. Finish with a short, accurate answer: what you did (with task ids), what failed or is still open.
   Never claim success for something that returned ok:false."""


class TaskAgent:
    def __init__(self, llm: LLM, executor: ToolExecutor, principal: dict[str, Any],
                 config: AgentConfig | None = None, run_store: RunStore | None = None,
                 session_id: str | None = None, on_event: Callable[[str, dict], None] | None = None):
        self.llm, self.executor, self.principal = llm, executor, principal
        self.cfg = config or AgentConfig()
        self.store = run_store or NullRunStore()
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.on_event = on_event or (lambda kind, data: None)
        self.specs = executor.available()
        self.tool_schemas = [s.openai_schema() for s in self.specs]
        self._entities = RunState(run_id="-")                       # working memory survives across user turns
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(
                name=principal["name"], email=principal["email"], role=principal["role"],
                today=date.today().isoformat())},
            {"role": "system", "content": self._entities.working_memory()},      # index 1 – rewritten each iteration
        ]

    # ══════════════════════════════════════════════════════════════════
    @tracing.observe(name="agent.run", as_type="agent", capture_input=False, capture_output=False)
    async def run(self, user_message: str) -> AgentResult:
        with tracing.propagate_attributes(user_id=self.principal["id"], session_id=self.session_id,
                                          trace_name="task-agent-run",
                                          tags=["task-agent", f"role:{self.principal['role']}"],
                                          metadata={"model": getattr(self.llm, "model", "unknown")}):
            return await self._run(user_message)

    async def _run(self, user_message: str) -> AgentResult:
        t0 = time.perf_counter()
        state = self._new_state()
        usage: dict[str, int] = {}
        self.messages.append({"role": "user", "content": user_message})
        tracing.trace_io(input=user_message)
        answer, stop_reason = None, None

        while answer is None and stop_reason is None:
            # ── guard 1: iteration budget ──────────────────────────────
            if state.iteration >= self.cfg.max_iterations:
                stop_reason = "max_iterations"
                break
            state.iteration += 1
            self.messages[1]["content"] = state.working_memory()

            # ── ask the LLM ────────────────────────────────────────────
            try:
                turn = await self.llm.chat(self.messages, self.tool_schemas)
            except Exception as e:                                           # provider outage etc.
                stop_reason = f"llm_error: {type(e).__name__}: {e}"
                break
            for k, v in turn.usage.items():
                usage[k] = usage.get(k, 0) + v
            self.messages.append(turn.as_message())
            self.on_event("llm", {"iteration": state.iteration, "tool_calls": [c.name for c in turn.tool_calls],
                                  "text": turn.content})

            if not turn.tool_calls:                                          # ── final answer ──
                answer = turn.content or ""
                break

            # ── guard 2: tool-call budget ──────────────────────────────
            if state.tool_calls + len(turn.tool_calls) > self.cfg.max_tool_calls:
                self._answer_all(turn.tool_calls, "budget_exceeded",
                                 "Tool-call budget for this request is used up.",
                                 "Stop calling tools and report progress to the user.")
                stop_reason = "max_tool_calls"
                break

            # ── execute (parallel / sequential handled inside) ─────────
            results = await self._execute_round(turn.tool_calls, state)
            state.tool_calls += len(turn.tool_calls)
            for call, res in zip(turn.tool_calls, results):
                self.messages.append({"role": "tool", "tool_call_id": call.id,
                                      "content": res.to_llm(self.cfg.max_result_chars)})
                state.ingest(res)

            # ── guard 3: loops and repeated failure ────────────────────
            if state.duplicates > self.cfg.max_duplicate_calls:
                stop_reason = "loop_detected"
            elif all(not r.ok for r in results):
                state.consecutive_failed_rounds += 1
                if state.consecutive_failed_rounds >= self.cfg.max_failed_rounds:
                    stop_reason = "repeated_failures"
            else:
                state.consecutive_failed_rounds = 0

        # ── graceful stop: tools OFF, ask for an honest summary ────────
        if answer is None:
            answer = await self._wrap_up(stop_reason, state, usage)

        status = self._status(stop_reason, state)
        self._entities.users, self._entities.tasks = state.users, state.tasks
        self._entities.prior_changes = state.prior_changes + state.changes
        result = AgentResult(status=status, answer=answer, stop_reason=stop_reason, run_id=state.run_id,
                             iterations=state.iteration, tool_calls=state.tool_calls, steps=state.steps,
                             changes=state.changes, usage=usage, trace_url=tracing.current_trace_url())
        tracing.trace_io(output=answer)
        tracing.score("agent_status", status, data_type="CATEGORICAL", comment=stop_reason)
        tracing.score("tool_calls", float(state.tool_calls), data_type="NUMERIC")
        await self.store.save({
            "run_id": state.run_id, "session_id": self.session_id, "user_id": self.principal["id"],
            "started_at": datetime.now(timezone.utc).isoformat(), "duration_ms": int((time.perf_counter() - t0) * 1000),
            "status": status, "stop_reason": stop_reason, "iterations": state.iteration,
            "tool_calls": state.tool_calls, "changes": state.changes, "usage": usage, "trace_url": result.trace_url,
            "steps": [s.__dict__ for s in state.steps], "user_message": user_message, "answer": answer,
            "messages": self.messages[2:]})
        return result

    # ══════════════════════════════════════════════════════════════════
    def _new_state(self) -> RunState:
        s = RunState(run_id=uuid.uuid4().hex[:12])
        s.users, s.tasks = deepcopy(self._entities.users), deepcopy(self._entities.tasks)
        s.prior_changes = list(self._entities.prior_changes)
        return s

    def _answer_all(self, calls: list[ToolCall], code: str, message: str, hint: str) -> list[ToolResult]:
        """The API requires EVERY tool_call_id to get a tool message – even ones we refuse to run."""
        out = []
        for c in calls:
            r = ToolResult(tool=c.name, call_id=c.id, ok=False,
                           error=ToolError(code=code, message=message, hint=hint))
            self.messages.append({"role": "tool", "tool_call_id": c.id, "content": r.to_llm()})
            out.append(r)
        return out

    async def _execute_round(self, calls: list[ToolCall], state: RunState) -> list[ToolResult]:
        """Split the model's calls into (a) duplicates we answer from cache / refuse, (b) real work."""
        results: dict[str, ToolResult] = {}
        to_run: list[ToolCall] = []
        for c in calls:
            spec = self.executor.registry.get(c.name)
            sig = state.signature(c.name, c.arguments, read_only=bool(spec and spec.read_only))
            state.signature_counts[sig] += 1
            if state.signature_counts[sig] == 1:
                to_run.append(c)
                continue
            state.duplicates += 1                                        # ← feeds the loop detector
            prev = state.result_cache.get(sig)
            if prev is not None and prev.ok and spec and spec.read_only:
                results[c.id] = prev.model_copy(update={"call_id": c.id, "cached": True,
                    "note": "Identical call already made and nothing changed since; returning the earlier "
                            "result. Use it instead of calling again."})
            else:
                results[c.id] = ToolResult(tool=c.name, call_id=c.id, ok=False, mutating=bool(spec and not spec.read_only),
                    error=ToolError(code="duplicate_call", message="This exact call was already made in this run.",
                                    hint="Do not repeat it. Use the earlier result, change your approach, or "
                                         "answer the user."))
        group_of: dict[str, int] = {}
        if to_run:
            batches = self.executor.plan_batches(to_run)
            for b in batches:
                if len(b) > 1:                                           # this batch runs concurrently
                    g = state.next_group()
                    group_of.update({c.id: g for c in b})
            self.on_event("tools", {"batches": [[c.name for c in b] for b in batches]})
            for c, r in zip(to_run, await self.executor.execute_batch(to_run, state.run_id)):
                results[c.id] = r
                spec = self.executor.registry.get(c.name)
                state.result_cache[state.signature(c.name, c.arguments, bool(spec and spec.read_only))] = r
        ordered = [results[c.id] for c in calls]
        for c, r in zip(calls, ordered):
            self.on_event("result", {"tool": c.name, "ok": r.ok, "cached": r.cached,
                                     "error": r.error.code if r.error else None, "attempts": r.attempts,
                                     "ms": r.duration_ms})
            state.steps.append(StepRecord(state.iteration, c.name, _loads(c.arguments), r.ok,
                                          r.error.code if r.error else None, r.attempts, r.duration_ms,
                                          r.cached, group_of.get(c.id)))
        return ordered

    def _status(self, stop_reason: str | None, state: RunState) -> Literal["completed", "partial", "failed"]:
        if stop_reason is None:
            return "completed"
        made_progress = bool(state.changes) or any(s.ok and not s.cached for s in state.steps)
        return "partial" if made_progress else "failed"

    async def _wrap_up(self, stop_reason: str | None, state: RunState, usage: dict) -> str:
        """Tools disabled → the model can only talk. Fallback to a template if even that fails."""
        note = {"role": "system", "content":
                f"STOP ({stop_reason}). You can no longer call tools. Write the final reply: what was completed "
                f"(with ids), what failed or remains, and what the user can do next. Do not claim anything you "
                f"did not verify."}
        try:
            turn: LLMTurn = await self.llm.chat(self.messages + [note], self.tool_schemas, tool_choice="none")
            for k, v in turn.usage.items():
                usage[k] = usage.get(k, 0) + v
            text = turn.content or ""
        except Exception:
            text = ""
        if not text:
            done = "; ".join(state.changes) or "no changes were made"
            text = (f"I had to stop early ({stop_reason}). Completed so far: {done}. "
                    f"Please check the remaining items or try again.")
        self.messages.append({"role": "assistant", "content": text})
        return text


def _loads(s: str):
    try:
        return json.loads(s)
    except Exception:
        return s
