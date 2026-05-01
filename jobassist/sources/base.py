"""Source protocol — the contract every job source must satisfy."""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from jobassist.schemas import JobPosting, JobQuery


@runtime_checkable
class Source(Protocol):
    """Any object that can search for job postings given a query."""

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Yield postings matching *query*, one at a time as they are fetched."""
        ...
