"""STATE BETWEEN CALLS.

The model is stateless: everything it "remembers" is the messages list we resend.  RunState is
OUR bookkeeping on top of that – budgets, loop detection, and a compact WORKING MEMORY of facts
discovered so far (user ids, task ids + versions) which we inject as a system message so the
model doesn't burn tool calls re-discovering them.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .results import ToolResult


@dataclass
class StepRecord:
    iteration: int
    tool: str
    args: Any
    ok: bool
    error_code: str | None
    attempts: int
    duration_ms: int
    cached: bool = False
    parallel_group: int | None = None      # calls sharing a group id ran concurrently


@dataclass
class RunState:
    run_id: str
    iteration: int = 0
    tool_calls: int = 0
    epoch: int = 0                          # +1 whenever a WRITE succeeds ("the world changed")
    duplicates: int = 0
    consecutive_failed_rounds: int = 0
    signature_counts: Counter = field(default_factory=Counter)
    result_cache: dict[str, ToolResult] = field(default_factory=dict)
    steps: list[StepRecord] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)       # successful writes in THIS run
    prior_changes: list[str] = field(default_factory=list)  # writes from earlier turns of the session
    users: dict[str, dict] = field(default_factory=dict)   # email → {id,name}
    tasks: dict[str, dict] = field(default_factory=dict)   # task id → brief
    _group_counter: int = 0

    def next_group(self) -> int:
        self._group_counter += 1
        return self._group_counter

    # ── loop detection ────────────────────────────────────────────────
    def signature(self, name: str, raw_args: str, read_only: bool) -> str:
        """Identity of a call.  Reads include `epoch`: re-reading AFTER a write is legitimate progress,
        re-reading with nothing changed is a loop.  Writes ignore epoch: the same write twice is never OK."""
        try:
            canon = json.dumps(json.loads(raw_args or "{}"), sort_keys=True)
        except json.JSONDecodeError:
            canon = raw_args
        return f"{name}|{canon}" + (f"|e{self.epoch}" if read_only else "")

    # ── working memory ────────────────────────────────────────────────
    def ingest(self, r: ToolResult) -> None:
        if not r.ok:
            # A version conflict PROVES someone else changed the data: cached reads are now stale, so
            # advance the epoch. (Other failed writes change nothing, so they don't.)
            if r.error and r.error.code == "version_conflict":
                self.epoch += 1
            return
        if r.cached:
            return
        d = r.data or {}
        if r.tool == "find_user":
            self.users[d["email"]] = {"id": d["id"], "name": d["name"]}
        elif r.tool == "list_tasks":
            for t in d.get("items", []):
                self._remember_task(t)
        elif r.tool in ("get_task", "create_task", "update_task"):
            self._remember_task(d)
        elif r.tool == "delete_task":
            self.tasks.pop(d.get("task_id"), None)
        if r.mutating:
            self.epoch += 1
            self.changes.append(self._describe_change(r))

    def _remember_task(self, t: dict) -> None:
        self.tasks[t["id"]] = {k: t.get(k) for k in ("title", "status", "priority", "due_date", "version", "owner_id")
                               if t.get(k) is not None}

    @staticmethod
    def _describe_change(r: ToolResult) -> str:
        d = r.data or {}
        if r.tool == "create_task":
            return f"created {d.get('id')} '{d.get('title')}'"
        if r.tool == "update_task":
            return f"updated {d.get('id')} (now status={d.get('status')}, priority={d.get('priority')}, v{d.get('version')})"
        return f"deleted {d.get('task_id')}"

    def working_memory(self, max_tasks: int = 15) -> str:
        lines = ["WORKING MEMORY – facts already established in this session. Reuse them; do not re-fetch "
                 "unless you need fresher data."]
        if not (self.users or self.tasks or self.prior_changes or self.changes):
            lines.append("(nothing yet)")
        for email, u in self.users.items():
            lines.append(f"- user {email} → id {u['id']} ({u['name']})")
        for tid, t in list(self.tasks.items())[-max_tasks:]:
            lines.append(f"- task {tid}: " + ", ".join(f"{k}={v}" for k, v in t.items()))
        all_changes = self.prior_changes + self.changes
        if all_changes:
            lines.append("Writes already performed (do NOT repeat them): " + "; ".join(all_changes[-10:]))
        return "\n".join(lines)
