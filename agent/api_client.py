"""Thin async HTTP client the tools use to reach FastAPI.

The agent authenticates as a specific user (bearer token) – so the SERVER stays the source of
truth for permissions.  Tool-level checks are an extra, earlier layer (defence in depth).
"""
from __future__ import annotations

from typing import Any

import httpx

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None,
                 retry_after: float | None = None, request_id: str | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message
        self.details = details or []
        self.retry_after = retry_after
        self.request_id = request_id
        

class ApiClient:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 10.0):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout,
                                       headers={"Authorization": f"Bearer {token}"})

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                      headers: dict | None = None) -> httpx.Response:
        """Returns the response for 2xx; raises ApiError for 4xx/5xx; lets httpx.TransportError
        (connect/read timeouts, resets) propagate – the executor decides whether to retry those."""
        resp = await self._http.request(method, path, params=params, json=json, headers=headers)
        if resp.status_code < 400:
            return resp
        code, message, details, rid = "upstream_error", resp.reason_phrase or "error", [], None
        try:
            err = resp.json()["error"]
            code, message, details, rid = err["code"], err["message"], err.get("details", []), err.get("request_id")
        except Exception:
            pass                                          # e.g. an HTML 502 from a proxy
        retry_after = None
        if "retry-after" in resp.headers:
            try:
                retry_after = float(resp.headers["retry-after"])
            except ValueError:
                pass
        raise ApiError(resp.status_code, code, message, details, retry_after, rid)

    async def aclose(self) -> None:
        await self._http.aclose()