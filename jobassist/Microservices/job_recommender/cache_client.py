"""In-process cache client for job_recommender.

job_recommender owns the `Store`, so its own LLM-caching code talks to the store
directly (no HTTP hop). Other services use their `RemoteCacheClient` to reach the
`/cache` endpoints this service exposes over that same store.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from jobassist.Microservices.job_recommender.persistence.store import Store


@runtime_checkable
class CacheClient(Protocol):
    """Minimal async cache interface the LLM-calling code depends on."""

    async def get_cached(self, key: str) -> str | None: ...
    async def set_cached(self, key: str, value: str) -> None: ...


def cache_key(*parts: str) -> str:
    """Return a sha256 hex digest of the concatenated *parts*, used as a cache key."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class LocalCacheClient:
    """Async cache facade over the local sync `Store`."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def get_cached(self, key: str) -> str | None:
        return self._store.get_cached(key)

    async def set_cached(self, key: str, value: str) -> None:
        self._store.set_cached(key, value)
