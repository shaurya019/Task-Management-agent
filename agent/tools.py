"""TOOLS = typed wrappers around the CRUD endpoints.

Each tool declares, in ONE place:
    name / description      → what the LLM sees
    args_model (Pydantic)   → JSON-Schema for the LLM  AND  validation of what the LLM sends back
    scope                   → TOOL PERMISSION  (required scope; tool is hidden from the LLM without it)
    read_only               → safe to cache / re-run
    parallel_safe           → may run concurrently with its neighbours
    handler                 → the HTTP call

Design rules that matter for LLM tool-use:
  • few, narrow tools with verbs the model already understands
  • descriptions say WHEN to use the tool and what NOT to do
  • update_task maps to PATCH (never PUT): a full-replace tool invites the model to clobber fields
  • destructive tools need an explicit `confirm=true` that the model may only set after the USER agrees
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Priority, TaskList, TaskOut, TaskStatus, UserOut

from .api_client import ApiClient


# ── local (non-HTTP) failure a handler can raise ───────────────────────────
class ToolRejected(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None, retryable: bool = True):
        super().__init__(message)
        self.code, self.message, self.hint, self.retryable = code, message, hint, retryable


@dataclass(frozen=True)
class CallContext:
    call_id: str
    idempotency_key: str        # stable across retries of ONE tool call → safe POST retries
    request_id: str             # sent as X-Request-ID → joins API logs with the Langfuse trace


# ── argument models (what the LLM must send) ───────────────────────────────
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateTaskArgs(_Args):
    title: str = Field(min_length=1, max_length=120, description="Short imperative title, e.g. 'Book flights'")
    description: str | None = Field(None, max_length=2000)
    priority: Priority = Priority.medium
    due_date: date | None = Field(None, description="ISO date YYYY-MM-DD")
    tags: list[str] = Field(default_factory=list, description="max 10 short lowercase tags")


class GetTaskArgs(_Args):
    task_id: str = Field(description="Task id such as 't_1a2b3c4d5e6f'. Never guess ids – find them with list_tasks.")


class UpdateTaskArgs(_Args):
    task_id: str
    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    due_date: date | None = Field(None, description="ISO date YYYY-MM-DD")
    tags: list[str] | None = None
    expected_version: int | None = Field(
        None, description="Version you last saw (from get_task/list_tasks). If the task changed meanwhile "
                          "the call fails with version_conflict instead of overwriting someone's work.")


class DeleteTaskArgs(_Args):
    task_id: str
    confirm: bool = Field(False, description="Set true ONLY after the user explicitly confirmed this deletion "
                                             "in the conversation. Otherwise ask the user first.")


class ListTasksArgs(_Args):
    status: TaskStatus | None = None
    priority: Priority | None = None
    tag: str | None = None
    text: str | None = Field(None, description="substring to match in the title")
    due_before: date | None = Field(None, description="only tasks due strictly before this date (YYYY-MM-DD)")
    owner_id: str | None = Field(None, description="ADMIN ONLY. User id (from find_user) whose tasks to list. "
                                                    "Omit to list your own.")
    sort_by: str = Field("created_at", pattern="^(created_at|updated_at|due_date|priority)$")
    order: str = Field("desc", pattern="^(asc|desc)$")
    limit: int = Field(20, ge=1, le=50)
    offset: int = Field(0, ge=0)


class FindUserArgs(_Args):
    email: str = Field(description="Exact email address of the user")


# ── handlers ───────────────────────────────────────────────────────────────
Handler = Callable[[ApiClient, Any, CallContext], Awaitable[Any]]


def _hdr(ctx: CallContext, **extra: str) -> dict[str, str]:
    return {"X-Request-ID": ctx.request_id, **extra}


async def _create(api: ApiClient, a: CreateTaskArgs, ctx: CallContext):
    r = await api.request("POST", "/tasks", json=a.model_dump(mode="json", exclude_none=True),
                          headers=_hdr(ctx, **{"Idempotency-Key": ctx.idempotency_key}))
    return TaskOut.model_validate(r.json()).model_dump(mode="json")      # RESPONSE VALIDATION on the client side


async def _get(api: ApiClient, a: GetTaskArgs, ctx: CallContext):
    r = await api.request("GET", f"/tasks/{a.task_id}", headers=_hdr(ctx))
    return TaskOut.model_validate(r.json()).model_dump(mode="json")


async def _update(api: ApiClient, a: UpdateTaskArgs, ctx: CallContext):
    body = a.model_dump(mode="json", exclude_none=True, exclude={"task_id", "expected_version"})
    if not body:
        raise ToolRejected("no_changes", "update_task called without any field to change.",
                           hint="Provide at least one of title/description/status/priority/due_date/tags.")
    extra = {"If-Match": f'"{a.expected_version}"'} if a.expected_version is not None else {}
    r = await api.request("PATCH", f"/tasks/{a.task_id}", json=body, headers=_hdr(ctx, **extra))
    return TaskOut.model_validate(r.json()).model_dump(mode="json")


async def _delete(api: ApiClient, a: DeleteTaskArgs, ctx: CallContext):
    if not a.confirm:
        raise ToolRejected("confirmation_required",
                           "Deleting is destructive and was not confirmed.",
                           hint="Ask the user to confirm deleting this task, then call delete_task again "
                                "with confirm=true.", retryable=True)
    await api.request("DELETE", f"/tasks/{a.task_id}", headers=_hdr(ctx))
    return {"deleted": True, "task_id": a.task_id}


async def _list(api: ApiClient, a: ListTasksArgs, ctx: CallContext):
    params = a.model_dump(mode="json", exclude_none=True)
    if "text" in params:
        params["q"] = params.pop("text")                               # tool arg name → API query name
    r = await api.request("GET", "/tasks", params=params, headers=_hdr(ctx))
    page = TaskList.model_validate(r.json())
    return {"items": [t.model_dump(mode="json") for t in page.items], "total": page.total,
            "has_more": page.has_more, **({"next_offset": page.offset + len(page.items)} if page.has_more else {})}


async def _find_user(api: ApiClient, a: FindUserArgs, ctx: CallContext):
    r = await api.request("GET", "/users", params={"email": a.email}, headers=_hdr(ctx))
    return UserOut.model_validate(r.json()).model_dump(mode="json")


# ── registry ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    scope: str
    read_only: bool
    parallel_safe: bool
    handler: Handler

    def openai_schema(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": _strip_titles(self.args_model.model_json_schema())}}


def _strip_titles(node: Any, in_properties: bool = False) -> Any:
    """Pydantic adds a 'title' to every schema node – noise that costs tokens."""
    if isinstance(node, dict):
        return {k: _strip_titles(v, in_properties=(k == "properties"))
                for k, v in node.items() if in_properties or k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


REGISTRY: dict[str, ToolSpec] = {s.name: s for s in [
    ToolSpec("list_tasks",
             "List tasks with optional filters, sorting and paging. Use this to FIND task ids and to answer "
             "'what is due / open / high priority'. Returns a compact page; check has_more.",
             ListTasksArgs, "tasks:read", read_only=True, parallel_safe=True, handler=_list),
    ToolSpec("get_task",
             "Fetch ONE task by id (full details + current version). Use before updating when you need the "
             "latest version.",
             GetTaskArgs, "tasks:read", read_only=True, parallel_safe=True, handler=_get),
    ToolSpec("create_task",
             "Create a new task. Idempotent per tool call, so retries never create duplicates. "
             "Do not create a task the user did not ask for.",
             CreateTaskArgs, "tasks:write", read_only=False, parallel_safe=True, handler=_create),
    ToolSpec("update_task",
             "Change fields of an existing task (partial update: only send what changes). Use status="
             "'done' to complete a task. Pass expected_version when you have it.",
             UpdateTaskArgs, "tasks:write", read_only=False, parallel_safe=False, handler=_update),
    ToolSpec("delete_task",
             "Permanently delete a task. DESTRUCTIVE: requires the user's explicit confirmation first.",
             DeleteTaskArgs, "tasks:delete", read_only=False, parallel_safe=False, handler=_delete),
    ToolSpec("find_user",
             "Look up a user by email to obtain their user id (needed for list_tasks(owner_id=...)). "
             "Only available to admins/support staff.",
             FindUserArgs, "users:lookup", read_only=True, parallel_safe=True, handler=_find_user),
]}


def tools_for_scopes(scopes: set[str] | frozenset[str]) -> list[ToolSpec]:
    """LEAST PRIVILEGE: the LLM is only *shown* tools its user may actually use."""
    return [s for s in REGISTRY.values() if s.scope in scopes]
