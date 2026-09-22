"""Pydantic models = the contract.  They do three jobs:
  1. validate REQUESTS   (TaskCreate / TaskReplace / TaskPatch, extra='forbid')
  2. validate + filter RESPONSES  (response_model=TaskOut hides internal fields)
  3. generate the JSON-Schema the LLM sees as tool definitions (agent/tools.py)
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    
class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    
Title = Annotated[str, Field(min_length=1, max_length=120, description="Short task title")]
Tag = Annotated[str, Field(min_length=1, max_length=30)]

class _TaskFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("tags", check_fields=False)
    @classmethod
    def _clean_tags(cls, v: list[str] | None):
        if v is None:
            return v
        cleaned = list(dict.fromkeys(t.strip().lower() for t in v))   # lower-case + de-dupe
        if len(cleaned) > 2:
            raise ValueError("at most 2 tags")
        return cleaned
    
class TaskCreate(_TaskFields):
    title:Title
    description: str | None = Field(None, max_length=2000)
    priority: Priority = Priority.medium
    due_date: date | None = None
    tags: list[Tag] = Field(default_factory=list)
    
class TaskReplace(_TaskFields):
    """PUT body – a FULL replacement: every field is required."""
    title: Title
    description: str | None
    status: TaskStatus
    priority: Priority
    due_date: date | None
    tags: list[Tag]
    

class TaskPatch(_TaskFields):
    """PATCH body – only the fields present in the JSON are changed."""
    title: Title | None = None
    description: str | None = Field(None, max_length=2000)
    status: TaskStatus | None = None
    priority: Priority | None = None
    due_date: date | None = None
    tags: list[Tag] | None = None

    @model_validator(mode="after")
    def _validate(self):
        if not self.model_fields_set:
            raise ValueError("PATCH body must contain at least one field")
        for f in ("title", "status", "priority", "tags"):        # these are not nullable
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f"'{f}' cannot be null")
        return self

    
class TaskOut(BaseModel):
    """What clients receive.  Internal columns (deleted_at, idempotency hash…) never appear."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    title: str
    description: str | None = None
    status: TaskStatus
    priority: Priority
    due_date: date | None = None
    tags: list[str] = []
    version: int = Field(description="Increments on every write – used for optimistic locking")
    created_at: datetime
    updated_at: datetime
    
    
class TaskRecord(TaskOut):
    """Repository-internal shape (superset of TaskOut)."""
    deleted_at: datetime | None = None


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str


class MeOut(UserOut):
    scopes: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = []
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody