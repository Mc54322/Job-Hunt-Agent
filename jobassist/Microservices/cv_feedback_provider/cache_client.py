"""Remote cache client for cv_feedback_provider.

The LLM response cache lives in the job_recommender service. This service reaches it
over HTTP (`POST /cache/get|set`). Caching is best-effort: if the cache service is
unreachable, calls degrade to a miss rather than failing the request.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

import httpx


@runtime_checkable
class CacheClient(Protocol):
    """Minimal async cache interface the LLM-calling code depends on."""

    async def get_cached(self, key: str) -> str | None: ...
    async def set_cached(self, key: str, value: str) -> None: ...


def cache_key(*parts: str) -> str:
    """Return a sha256 hex digest of the concatenated *parts*, used as a cache key."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class RemoteCacheClient:
    """Async cache facade over the job_recommender `/cache` endpoints."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = client

    async def get_cached(self, key: str) -> str | None:
        try:
            resp = await self._http.post(f"{self._base}/cache/get", json={"key": key})
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        value = resp.json().get("value")
        return str(value) if value is not None else None

    async def set_cached(self, key: str, value: str) -> None:
        try:
            resp = await self._http.post(
                f"{self._base}/cache/set", json={"key": key, "value": value}
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return
