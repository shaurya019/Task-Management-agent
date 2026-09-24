"""Repository interface.  The FastAPI routes only know THIS – swapping SQLite for MongoDB
is a one-line change in the app factory (DB_BACKEND=mongo)."""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from ..schemas import Priority, TaskCreate, TaskRecord, TaskReplace, TaskStatus

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class TaskQuery:
    owner_id: str | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    tag: str | None = None
    text: str | None = None
    due_before: date | None = None
    sort_by: str = "created_at"          # created_at | updated_at | due_date | priority
    order: str = "desc"                  # asc | desc
    limit: int = 20
    offset: int = 0


def request_hash(data: TaskCreate) -> str:
    """Fingerprint of a create-request body – used to detect Idempotency-Key reuse with a
    DIFFERENT payload (that is a client bug, must not silently return the old result)."""
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class TaskRepository(ABC):
    @abstractmethod
    def init(self) -> None: ...

    @abstractmethod
    def create(self, owner_id: str, data: TaskCreate,
               idempotency_key: str | None = None) -> tuple[TaskRecord, bool]:
        """→ (task, replayed).  Raises QuotaExceeded, IdempotencyKeyReused."""

    @abstractmethod
    def get(self, task_id: str, include_deleted: bool = False) -> TaskRecord | None:
        """Task or None.  Soft-deleted tasks are hidden unless include_deleted=True."""

    @abstractmethod
    def list(self, q: TaskQuery) -> tuple[list[TaskRecord], int]: ...

    @abstractmethod
    def replace(self, task_id: str, data: TaskReplace, expected_version: int,
                actor_id: str) -> TaskRecord:
        """PUT.  Raises TaskNotFound, VersionConflict."""

    @abstractmethod
    def patch(self, task_id: str, changes: dict, expected_version: int | None,
              actor_id: str) -> TaskRecord:
        """PATCH.  `changes` is JSON-safe, only touched fields.  Raises TaskNotFound, VersionConflict."""

    @abstractmethod
    def delete(self, task_id: str, actor_id: str) -> bool:
        """Soft delete.  True = deleted now, False = was already deleted (idempotent).
        Raises TaskNotFound if the id never existed."""

    @abstractmethod
    def events(self, task_id: str) -> list[dict]:
        """Audit trail (written in the SAME transaction as each change)."""
