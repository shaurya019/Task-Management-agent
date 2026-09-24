"""One error type + one JSON envelope for the whole API.

Every error the client ever sees looks like:
    {"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}
so the agent (a machine) can branch on `code` instead of parsing prose.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """HTTP-level error – carries status + machine-readable code."""

    def __init__(self, status: int, code: str, message: str,
                 details: list[dict[str, Any]] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers or {}


# ── domain exceptions raised by repositories (HTTP-agnostic) ──────────────
class TaskNotFound(Exception):
    ...


class VersionConflict(Exception):
    def __init__(self, current: int):
        super().__init__(f"current version is {current}")
        self.current = current


class IdempotencyKeyReused(Exception):
    ...


class QuotaExceeded(Exception):
    ...
