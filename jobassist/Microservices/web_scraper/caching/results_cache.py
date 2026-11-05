"""Saved search results — re-running a search reuses recent results per company/source
instead of re-fetching every board and website (and re-paying for LLM extraction).

Entries are stored through the shared response cache as JSON with a ``saved_at``
timestamp and expire after ``max_age``. ``refresh=True`` skips reading saved results
(a forced fresh search) but still saves what it fetches, so the next normal run is fast.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Sequence

from jobassist.Microservices.web_scraper.cache_client import CacheClient, cache_key
from jobassist.Microservices.web_scraper.models.schemas import JobPosting

DEFAULT_MAX_AGE = timedelta(hours=24)


class ResultsCache:
    """Read-through cache of fetched postings, keyed by what was searched."""

    def __init__(
        self,
        cache: CacheClient,
        *,
        max_age: timedelta = DEFAULT_MAX_AGE,
        refresh: bool = False,
    ) -> None:
        self._cache = cache
        self._max_age = max_age
        self._refresh = refresh

    async def get_or_fetch(
        self,
        parts: Sequence[str],
        fetch: Callable[[], Awaitable[list[JobPosting]]],
    ) -> tuple[list[JobPosting], bool]:
        """Return ``(postings, from_cache)`` for the search identified by *parts*."""
        key = cache_key("results_v1", *parts)
        if not self._refresh:
            saved = await self._load(key)
            if saved is not None:
                return saved, True
        postings = await fetch()
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "postings": [p.model_dump(mode="json") for p in postings],
        }
        await self._cache.set_cached(key, json.dumps(payload))
        return postings, False

    async def _load(self, key: str) -> list[JobPosting] | None:
        raw = await self._cache.get_cached(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            saved_at = datetime.fromisoformat(data["saved_at"])
            if datetime.now(timezone.utc) - saved_at > self._max_age:
                return None
            return [JobPosting.model_validate(p) for p in data["postings"]]
        except (ValueError, KeyError, TypeError):
            return None
