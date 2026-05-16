"""Tests for the Adzuna aggregator fetcher — HTTP layer mocked via respx."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from jobassist.schemas import JobPosting, JobQuery
from jobassist.sources.adzuna import AdzunaFetcher, _format_salary
from jobassist.sources.base import Source

_FIXTURES = Path(__file__).parent / "fixtures"
_P1: dict = json.loads((_FIXTURES / "adzuna_search_p1.json").read_text())
_P2: dict = json.loads((_FIXTURES / "adzuna_search_p2.json").read_text())
_EMPTY: dict = {"count": 0, "results": []}

_QUERY = JobQuery(role="Software Engineer", job_type="full-time", location="London")
_QUERY_NO_LOC = JobQuery(role="Software Engineer", job_type="full-time")

_PAGE1_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
_PAGE2_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/2"


def _make_fetcher(results_per_page: int = 50) -> AdzunaFetcher:
    return AdzunaFetcher(
        httpx.AsyncClient(),
        app_id="test-id",
        app_key="test-key",
        results_per_page=results_per_page,
    )


async def _collect(fetcher: AdzunaFetcher, query: JobQuery) -> list[JobPosting]:
    results: list[JobPosting] = []
    async for posting in await fetcher.search(query):
        results.append(posting)
    return results


# ---------------------------------------------------------------------------
# Salary formatting
# ---------------------------------------------------------------------------


def test_format_salary_both() -> None:
    assert _format_salary(50000.0, 70000.0) == "£50,000 - £70,000"


def test_format_salary_min_only() -> None:
    assert _format_salary(50000.0, None) == "£50,000+"


def test_format_salary_max_only() -> None:
    assert _format_salary(None, 70000.0) == "up to £70,000"


def test_format_salary_neither() -> None:
    assert _format_salary(None, None) is None


# ---------------------------------------------------------------------------
# Basic search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_yields_postings() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_P1))
    respx.get(_PAGE2_URL).mock(return_value=httpx.Response(200, json=_EMPTY))
    results = await _collect(_make_fetcher(results_per_page=2), _QUERY)
    assert len(results) == 2
    assert all(p.source == "adzuna" for p in results)


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_posting_fields() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_P1))
    respx.get(_PAGE2_URL).mock(return_value=httpx.Response(200, json=_EMPTY))
    results = await _collect(_make_fetcher(results_per_page=2), _QUERY)
    p = results[0]
    assert p.company == "TechCorp Ltd"
    assert p.role == "Software Engineer"
    assert p.location == "London"
    assert p.url == "https://www.adzuna.co.uk/jobs/details/adzuna-001"
    assert p.salary_raw == "£50,000 - £70,000"
    assert p.posted_date is not None


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_respects_max_results() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_P1))
    query = JobQuery(role="Software Engineer", job_type="full-time", max_results=1)
    results = await _collect(_make_fetcher(results_per_page=2), query)
    assert len(results) == 1


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_paginates_when_page_is_full() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_P1))
    respx.get(_PAGE2_URL).mock(return_value=httpx.Response(200, json=_P2))
    # results_per_page=2 matches p1 exactly, so fetcher requests page 2
    query = JobQuery(role="Software Engineer", job_type="full-time", max_results=10)
    results = await _collect(_make_fetcher(results_per_page=2), query)
    assert len(results) == 3


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_stops_on_empty_results() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_EMPTY))
    results = await _collect(_make_fetcher(), _QUERY)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_handles_http_error() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(500))
    results = await _collect(_make_fetcher(), _QUERY)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_works_without_location() -> None:
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=_P1))
    respx.get(_PAGE2_URL).mock(return_value=httpx.Response(200, json=_EMPTY))
    results = await _collect(_make_fetcher(results_per_page=2), _QUERY_NO_LOC)
    assert len(results) == 2


@pytest.mark.asyncio
@respx.mock
async def test_adzuna_missing_salary_stored_as_none() -> None:
    no_salary = {
        "count": 1,
        "results": [
            {
                "id": "x",
                "title": "Software Engineer",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "London"},
                "redirect_url": "https://example.com/job/x",
                "created": "2024-01-15T10:00:00Z",
                "description": "Role with no salary.",
            }
        ],
    }
    respx.get(_PAGE1_URL).mock(return_value=httpx.Response(200, json=no_salary))
    results = await _collect(_make_fetcher(), _QUERY)
    assert results[0].salary_raw is None


def test_adzuna_satisfies_source_protocol() -> None:
    assert isinstance(_make_fetcher(), Source)
