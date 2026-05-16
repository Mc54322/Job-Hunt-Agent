"""Tests for the deduplication logic."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from jobassist.dedupe import ATS_SOURCES, deduplicate
from jobassist.schemas import JobPosting

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posting(
    company: str = "Acme",
    role: str = "Software Engineer",
    location: str = "London, UK",
    source: str = "greenhouse",
    url: str = "https://example.com/job/1",
) -> JobPosting:
    return JobPosting(
        company=company,
        role=role,
        location=location,
        url=url,
        source=source,
        salary_raw=None,
    )


async def _stream(*postings: JobPosting) -> AsyncIterator[JobPosting]:
    for p in postings:
        yield p


async def _collect(stream: AsyncIterator[JobPosting]) -> list[JobPosting]:
    return [p async for p in deduplicate(stream)]


# ---------------------------------------------------------------------------
# ATS_SOURCES registry
# ---------------------------------------------------------------------------


def test_ats_sources_contains_greenhouse_and_lever() -> None:
    assert "greenhouse" in ATS_SOURCES
    assert "lever" in ATS_SOURCES


def test_adzuna_not_in_ats_sources() -> None:
    assert "adzuna" not in ATS_SOURCES


# ---------------------------------------------------------------------------
# Basic deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unique_postings_pass_through() -> None:
    p1 = _posting(company="Acme", url="https://example.com/1")
    p2 = _posting(company="BetaCorp", url="https://example.com/2")
    results = await _collect(_stream(p1, p2))
    assert len(results) == 2


@pytest.mark.asyncio
async def test_empty_stream_yields_nothing() -> None:
    results = await _collect(_stream())
    assert results == []


@pytest.mark.asyncio
async def test_exact_duplicate_yields_once() -> None:
    p = _posting()
    results = await _collect(_stream(p, p))
    assert len(results) == 1


@pytest.mark.asyncio
async def test_same_hash_different_url_yields_once() -> None:
    # Same company/role/location → same hash, even if URL differs
    p1 = _posting(url="https://boards.greenhouse.io/acme/jobs/1")
    p2 = _posting(url="https://www.adzuna.co.uk/jobs/details/999", source="adzuna")
    results = await _collect(_stream(p1, p2))
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Priority: ATS-direct beats aggregator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ats_seen_first_is_kept() -> None:
    ats = _posting(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1")
    agg = _posting(source="adzuna", url="https://www.adzuna.co.uk/jobs/details/999")
    results = await _collect(_stream(ats, agg))
    assert results[0].source == "greenhouse"


@pytest.mark.asyncio
async def test_aggregator_seen_first_is_upgraded_to_ats() -> None:
    agg = _posting(source="adzuna", url="https://www.adzuna.co.uk/jobs/details/999")
    ats = _posting(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1")
    results = await _collect(_stream(agg, ats))
    assert len(results) == 1
    assert results[0].source == "greenhouse"


@pytest.mark.asyncio
async def test_lever_beats_adzuna() -> None:
    agg = _posting(source="adzuna", url="https://www.adzuna.co.uk/jobs/details/999")
    ats = _posting(source="lever", url="https://jobs.lever.co/acme/abc-001")
    results = await _collect(_stream(agg, ats))
    assert results[0].source == "lever"


@pytest.mark.asyncio
async def test_first_ats_wins_over_second_ats() -> None:
    gh = _posting(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1")
    lv = _posting(source="lever", url="https://jobs.lever.co/acme/abc-001")
    results = await _collect(_stream(gh, lv))
    assert results[0].source == "greenhouse"


@pytest.mark.asyncio
async def test_aggregator_does_not_replace_aggregator() -> None:
    agg1 = _posting(source="adzuna", url="https://www.adzuna.co.uk/jobs/details/1")
    agg2 = _posting(source="adzuna", url="https://www.adzuna.co.uk/jobs/details/2")
    results = await _collect(_stream(agg1, agg2))
    assert len(results) == 1
    assert results[0].url == agg1.url  # first seen wins


# ---------------------------------------------------------------------------
# Multi-posting scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_stream_deduplicates_correctly() -> None:
    unique1 = _posting(company="Acme", url="https://example.com/1")
    unique2 = _posting(company="BetaCorp", url="https://example.com/2")
    dup_agg = _posting(company="Acme", source="adzuna", url="https://adzuna.com/1")
    results = await _collect(_stream(unique1, unique2, dup_agg))
    assert len(results) == 2
    acme = next(r for r in results if r.company == "Acme")
    assert acme.source == "greenhouse"
