"""Tests for the Source protocol."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from jobassist.schemas import JobPosting, JobQuery
from jobassist.sources.base import Source

_QUERY = JobQuery(role="Software Engineer", job_type="full-time")

_POSTING = JobPosting(
    company="Acme Corp",
    role="Software Engineer",
    location="London, UK",
    url="https://example.com/job/1",
    source="stub",
)


class _ConformingSource:
    """Minimal Source implementation that yields one posting."""

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        async def _gen() -> AsyncIterator[JobPosting]:
            yield _POSTING

        return _gen()


class _EmptySource:
    """Source that yields nothing."""

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        async def _gen() -> AsyncIterator[JobPosting]:
            return
            yield  # makes _gen an async generator

        return _gen()


class _MissingSearchMethod:
    """Object that does NOT implement search — must not satisfy the protocol."""
    pass


def test_conforming_source_satisfies_protocol() -> None:
    assert isinstance(_ConformingSource(), Source)


def test_missing_search_does_not_satisfy_protocol() -> None:
    assert not isinstance(_MissingSearchMethod(), Source)


@pytest.mark.asyncio
async def test_conforming_source_yields_postings() -> None:
    source = _ConformingSource()
    results: list[JobPosting] = []
    async for posting in await source.search(_QUERY):
        results.append(posting)
    assert len(results) == 1
    assert results[0].company == "Acme Corp"


@pytest.mark.asyncio
async def test_empty_source_yields_nothing() -> None:
    source = _EmptySource()
    results: list[JobPosting] = []
    async for posting in await source.search(_QUERY):
        results.append(posting)
    assert results == []


@pytest.mark.asyncio
async def test_postings_are_job_posting_instances() -> None:
    source = _ConformingSource()
    async for posting in await source.search(_QUERY):
        assert isinstance(posting, JobPosting)
