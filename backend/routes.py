"""HTTP layer.  Each handler follows the same 5 steps:

   1. AUTHENTICATE   (Depends(get_principal) – inside require_scopes)
   2. AUTHORIZE      (scope via require_scopes, ownership via _load_owned)
   3. VALIDATE       (Pydantic body / Query / Header parsing – automatic 422)
   4. EXECUTE        (repository call – transactional)
   5. SHAPE RESPONSE (response_model → validated + filtered)
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from .auth import DIRECTORY, Principal, get_principal, require_scopes
from .db.base import TaskQuery, TaskRepository
from .errors import (AppError, IdempotencyKeyReused, QuotaExceeded, TaskNotFound, VersionConflict)
from .schemas import (MeOut, Priority, TaskCreate, TaskList, TaskOut, TaskPatch, TaskRecord,
                      TaskReplace, TaskStatus, UserOut)

router = APIRouter()


# ── dependencies / helpers ─────────────────────────────────────────────────
def get_repo(request: Request) -> TaskRepository:
    return request.app.state.repo


def _load_owned(repo: TaskRepository, task_id: str, principal: Principal,
                include_deleted: bool = False) -> TaskRecord:
    """Object-level authorization.  Someone else's task → 404 (not 403) so ids can't be probed."""
    task = repo.get(task_id, include_deleted=include_deleted)
    if task is None or (task.owner_id != principal.id and not principal.is_admin):
        raise AppError(404, "task_not_found", f"Task '{task_id}' was not found")
    return task


def _parse_if_match(value: str | None, required: bool) -> int | None:
    if value is None:
        if required:
            raise AppError(428, "precondition_required",
                           "PUT replaces the whole task, so an If-Match header with the task's current "
                           "version is required (get it from GET /tasks/{id} → 'version' or the ETag).")
        return None
    try:
        return int(value.strip().strip('"'))
    except ValueError:
        raise AppError(400, "invalid_if_match", "If-Match must be the integer version, e.g. If-Match: \"3\"")


def _etag(response: Response, task: TaskRecord) -> None:
    response.headers["ETag"] = f'"{task.version}"'


def _map_conflict(e: VersionConflict) -> AppError:
    return AppError(412, "version_conflict",
                    "The task was modified by someone else since you read it. "
                    "Re-fetch it (GET) and re-apply your change.",
                    details=[{"current_version": e.current}])


# ── meta ───────────────────────────────────────────────────────────────────
@router.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@router.get("/auth/me", response_model=MeOut, tags=["auth"])
def me(principal: Principal = Depends(get_principal)):
    return MeOut(id=principal.id, name=principal.name, email=principal.email,
                 role=principal.role, scopes=sorted(principal.scopes))


@router.get("/users", response_model=UserOut, tags=["users"])
def find_user(email: str = Query(..., min_length=3, max_length=200),
              _: Principal = Depends(require_scopes("users:lookup"))):
    user = DIRECTORY.get(email.strip().lower())
    if not user:
        raise AppError(404, "user_not_found", f"No user with email '{email}'")
    return UserOut(id=user.id, name=user.name, email=user.email, role=user.role)


# ── POST /tasks ────────────────────────────────────────────────────────────
@router.post("/tasks", response_model=TaskOut, status_code=201, tags=["tasks"])
def create_task(
    body: TaskCreate,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", min_length=1, max_length=128),
    principal: Principal = Depends(require_scopes("tasks:write")),
    repo: TaskRepository = Depends(get_repo),
):
    try:
        task, replayed = repo.create(principal.id, body, idempotency_key)
    except IdempotencyKeyReused:
        raise AppError(422, "idempotency_key_reuse",
                       "This Idempotency-Key was already used with a different request body.")
    except QuotaExceeded:
        raise AppError(409, "quota_exceeded", "Task limit reached – delete some tasks first.")
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    _etag(response, task)
    return task


# ── GET /tasks ─────────────────────────────────────────────────────────────
@router.get("/tasks", response_model=TaskList, tags=["tasks"])
def list_tasks(
    status: TaskStatus | None = None,
    priority: Priority | None = None,
    tag: str | None = Query(None, max_length=30),
    q: str | None = Query(None, max_length=100, description="substring match on title"),
    due_before: date | None = None,
    owner_id: str | None = Query(None, description="admin only: list another user's tasks"),
    sort_by: str = Query("created_at", pattern="^(created_at|updated_at|due_date|priority)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_scopes("tasks:read")),
    repo: TaskRepository = Depends(get_repo),
):
    if principal.is_admin:
        scope_owner = owner_id                       # None ⇒ all users
    elif owner_id in (None, principal.id):
        scope_owner = principal.id                   # members only ever see their own rows
    else:
        raise AppError(403, "forbidden_owner_filter", "You may only list your own tasks.")
    items, total = repo.list(TaskQuery(owner_id=scope_owner, status=status, priority=priority, tag=tag,
                                       text=q, due_before=due_before, sort_by=sort_by, order=order,
                                       limit=limit, offset=offset))
    return TaskList(items=items, total=total, limit=limit, offset=offset,
                    has_more=offset + len(items) < total)


# ── GET /tasks/{id} ────────────────────────────────────────────────────────
@router.get("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def get_task(task_id: str, response: Response,
             principal: Principal = Depends(require_scopes("tasks:read")),
             repo: TaskRepository = Depends(get_repo)):
    task = _load_owned(repo, task_id, principal)
    _etag(response, task)
    return task


# ── PUT /tasks/{id}  (full replace, optimistic lock REQUIRED) ──────────────
@router.put("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def replace_task(task_id: str, body: TaskReplace, response: Response,
                 if_match: str | None = Header(None, alias="If-Match"),
                 principal: Principal = Depends(require_scopes("tasks:write")),
                 repo: TaskRepository = Depends(get_repo)):
    version = _parse_if_match(if_match, required=True)
    _load_owned(repo, task_id, principal)
    try:
        task = repo.replace(task_id, body, version, principal.id)
    except TaskNotFound:
        raise AppError(404, "task_not_found", f"Task '{task_id}' was not found")
    except VersionConflict as e:
        raise _map_conflict(e)
    _etag(response, task)
    return task


# ── PATCH /tasks/{id}  (partial, If-Match optional) ────────────────────────
@router.patch("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def patch_task(task_id: str, body: TaskPatch, response: Response,
               if_match: str | None = Header(None, alias="If-Match"),
               principal: Principal = Depends(require_scopes("tasks:write")),
               repo: TaskRepository = Depends(get_repo)):
    version = _parse_if_match(if_match, required=False)
    _load_owned(repo, task_id, principal)
    try:
        task = repo.patch(task_id, body.model_dump(mode="json", exclude_unset=True), version, principal.id)
    except TaskNotFound:
        raise AppError(404, "task_not_found", f"Task '{task_id}' was not found")
    except VersionConflict as e:
        raise _map_conflict(e)
    _etag(response, task)
    return task


# ── DELETE /tasks/{id}  (idempotent) ───────────────────────────────────────
@router.delete("/tasks/{task_id}", status_code=204, tags=["tasks"])
def delete_task(task_id: str,
                principal: Principal = Depends(require_scopes("tasks:delete")),
                repo: TaskRepository = Depends(get_repo)):
    _load_owned(repo, task_id, principal, include_deleted=True)     # ownership check even for tombstones
    try:
        repo.delete(task_id, principal.id)                          # True/False both mean "it's gone"
    except TaskNotFound:
        raise AppError(404, "task_not_found", f"Task '{task_id}' was not found")
    return Response(status_code=204)
