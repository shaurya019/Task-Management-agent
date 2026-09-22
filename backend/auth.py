"""MOCK authentication + authorization.

Authentication  = "who are you?"           → Bearer token  → Principal      (401 if bad)
Authorization   = "what may you do?"
    • scope check   (coarse, per endpoint)  → 403 missing_scope
    • ownership     (fine, per object)      → 404 (hide existence) – see routes.py
A real system would verify a JWT / call an IdP; the dependency signature stays identical.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import AppError


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    email: str
    role: str                      # "member" | "viewer" | "admin"
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


MEMBER = frozenset({"tasks:read", "tasks:write", "tasks:delete"})
VIEWER = frozenset({"tasks:read"})
ADMIN = frozenset({"tasks:read", "tasks:write", "tasks:delete", "users:lookup"})

# token → principal   (our fake "identity provider")
TOKENS: dict[str, Principal] = {
    "token-alice":        Principal("u_alice", "Alice", "alice@example.com", "member", MEMBER),
    "token-bob":          Principal("u_bob",   "Bob",   "bob@example.com",   "member", MEMBER),
    "token-carol-viewer": Principal("u_carol", "Carol", "carol@example.com", "viewer", VIEWER),
    "token-admin":        Principal("u_admin", "Admin", "admin@example.com", "admin",  ADMIN),
}
DIRECTORY = {p.email: p for p in TOKENS.values()}          # used by GET /users?email=

_bearer = HTTPBearer(auto_error=False)   # we raise our own 401 so the JSON envelope stays consistent


def get_principal(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None:
        raise AppError(401, "unauthenticated", "Missing bearer token",
                       headers={"WWW-Authenticate": "Bearer"})
    principal = TOKENS.get(creds.credentials)
    if principal is None:
        raise AppError(401, "invalid_token", "Bearer token is not valid",
                       headers={"WWW-Authenticate": "Bearer"})
    return principal


def require_scopes(*needed: str):
    """Dependency factory:  Depends(require_scopes('tasks:write'))"""
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [s for s in needed if s not in principal.scopes]
        if missing:
            raise AppError(403, "missing_scope",
                           f"This action requires scope(s): {', '.join(missing)}",
                           details=[{"required": list(needed), "granted": sorted(principal.scopes)}])
        return principal
    return dependency
