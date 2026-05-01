"""Tests for Greenhouse and Lever ATS fetchers — HTTP layer mocked via respx."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from jobassist.schemas import JobPosting, JobQuery
from jobassist.sources.base import Source
from jobassist.sources.greenhouse import GreenhouseFetcher, _role_matches, _slugify
from jobassist.sources.lever import LeverFetcher

_FIXTURES = Path(__file__).parent / "fixtures"

_GH_FIXTURE: dict = json.loads((_FIXTURES / "greenhouse_acme.json").read_text())
_LV_FIXTURE: list = json.loads((_FIXTURES / "lever_acme.json").read_text())

_QUERY_SE = JobQuery(role="Software Engineer", job_type="full-time", companies=["Acme"])
_QUERY_EMPTY = JobQuery(role="Software Engineer", job_type="full-time")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


async def _collect(fetcher: GreenhouseFetcher | LeverFetcher, query: JobQuery) -> list[JobPosting]:
    results: list[JobPosting] = []
    async for posting in await fetcher.search(query):
        results.append(posting)
    return results


# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------


def test_slugify_lowercases() -> None:
    assert _slugify("Acme Corp") == "acme-corp"


def test_slugify_single_word() -> None:
    assert _slugify("DeepMind") == "deepmind"


# ---------------------------------------------------------------------------
# Role matching
# ---------------------------------------------------------------------------


def test_role_matches_exact() -> None:
    assert _role_matches("Software Engineer", "Software Engineer")


def test_role_matches_senior_prefix() -> None:
    assert _role_matches("Senior Software Engineer", "Software Engineer")


def test_role_matches_case_insensitive() -> None:
    assert _role_matches("SOFTWARE ENGINEER", "software engineer")


def test_role_no_match() -> None:
    assert not _role_matches("Data Analyst", "Software Engineer")


# ---------------------------------------------------------------------------
# Greenhouse fetcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_yields_matching_postings() -> None:
    respx.get("https://boards.greenhouse.io/acme/embed/job_board?format=json").mock(
        return_value=httpx.Response(200, json=_GH_FIXTURE)
    )
    results = await _collect(GreenhouseFetcher(_make_client()), _QUERY_SE)
    assert len(results) == 2
    assert all(p.source == "greenhouse" for p in results)
    assert all("Software Engineer" in p.role for p in results)


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_filters_non_matching_roles() -> None:
    respx.get("https://boards.greenhouse.io/acme/embed/job_board?format=json").mock(
        return_value=httpx.Response(200, json=_GH_FIXTURE)
    )
    query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Acme"])
    results = await _collect(GreenhouseFetcher(_make_client()), query)
    assert len(results) == 1
    assert results[0].role == "Data Analyst"


@pytest.mark.asyncio
async def test_greenhouse_empty_companies_yields_nothing() -> None:
    results = await _collect(GreenhouseFetcher(_make_client()), _QUERY_EMPTY)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_skips_404_company() -> None:
    respx.get("https://boards.greenhouse.io/acme/embed/job_board?format=json").mock(
        return_value=httpx.Response(404)
    )
    results = await _collect(GreenhouseFetcher(_make_client()), _QUERY_SE)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_posting_fields() -> None:
    respx.get("https://boards.greenhouse.io/acme/embed/job_board?format=json").mock(
        return_value=httpx.Response(200, json=_GH_FIXTURE)
    )
    results = await _collect(GreenhouseFetcher(_make_client()), _QUERY_SE)
    p = results[0]
    assert p.company == "Acme"
    assert p.url.startswith("https://boards.greenhouse.io/acme/jobs/")
    assert p.posted_date is not None
    assert p.hash == p.hash  # computed field is stable


@pytest.mark.asyncio
@respx.mock
async def test_greenhouse_satisfies_source_protocol() -> None:
    assert isinstance(GreenhouseFetcher(_make_client()), Source)


# ---------------------------------------------------------------------------
# Lever fetcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_lever_yields_matching_postings() -> None:
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").mock(
        return_value=httpx.Response(200, json=_LV_FIXTURE)
    )
    results = await _collect(LeverFetcher(_make_client()), _QUERY_SE)
    assert len(results) == 1
    assert results[0].role == "Software Engineer"
    assert results[0].source == "lever"


@pytest.mark.asyncio
@respx.mock
async def test_lever_filters_non_matching_roles() -> None:
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").mock(
        return_value=httpx.Response(200, json=_LV_FIXTURE)
    )
    query = JobQuery(role="Product Manager", job_type="full-time", companies=["Acme"])
    results = await _collect(LeverFetcher(_make_client()), query)
    assert len(results) == 1
    assert results[0].role == "Product Manager"


@pytest.mark.asyncio
async def test_lever_empty_companies_yields_nothing() -> None:
    results = await _collect(LeverFetcher(_make_client()), _QUERY_EMPTY)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_lever_skips_404_company() -> None:
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").mock(
        return_value=httpx.Response(404)
    )
    results = await _collect(LeverFetcher(_make_client()), _QUERY_SE)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_lever_posting_fields() -> None:
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").mock(
        return_value=httpx.Response(200, json=_LV_FIXTURE)
    )
    results = await _collect(LeverFetcher(_make_client()), _QUERY_SE)
    p = results[0]
    assert p.company == "Acme"
    assert p.url.startswith("https://jobs.lever.co/acme/")
    assert p.posted_date is not None
    assert p.location == "London, UK"


@pytest.mark.asyncio
@respx.mock
async def test_lever_satisfies_source_protocol() -> None:
    assert isinstance(LeverFetcher(_make_client()), Source)
