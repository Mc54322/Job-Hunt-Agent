"""Tests for the Workday ATS fetcher."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from jobassist.schemas import JobPosting, JobQuery
from jobassist.sources.workday import WorkdayFetcher

_FIXTURES = Path(__file__).parent / "fixtures"

_QUERY = JobQuery(
    role="Software Engineer",
    job_type="full-time",
    location="London, UK",
    max_results=50,
)

_COMPANY = "Acme"
_TENANT = "acme"
_SITE = "External"
_WD = "wd3"
_API_URL = f"https://{_TENANT}.{_WD}.myworkdayjobs.com/wday/cxs/{_TENANT}/{_SITE}/jobs"


@pytest.fixture
def workday_payload() -> dict:  # type: ignore[type-arg]
    return json.loads((_FIXTURES / "workday_jobs.json").read_text())


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


# ---------------------------------------------------------------------------
# Basic fetching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_returns_matching_postings(workday_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=workday_payload))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    # Fixture has 3 jobs; 2 have "Software Engineer" in title
    assert len(results) == 2
    assert all(isinstance(p, JobPosting) for p in results)


@pytest.mark.asyncio
@respx.mock
async def test_posting_fields_are_correct(workday_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=workday_payload))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    first = results[0]
    assert first.company == _COMPANY
    assert first.source == "workday"
    assert _TENANT in first.url
    assert first.url.startswith("https://")


@pytest.mark.asyncio
@respx.mock
async def test_url_includes_external_path(workday_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=workday_payload))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert "JR12345" in results[0].url


@pytest.mark.asyncio
@respx.mock
async def test_location_is_populated(workday_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=workday_payload))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results[0].location == "London, United Kingdom"


# ---------------------------------------------------------------------------
# Role filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_filters_non_matching_roles(client: httpx.AsyncClient) -> None:
    payload = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Marketing Manager",
                "externalPath": "/en-US/External/job/London/Marketing-Manager_JR99",
                "locationsText": "London, United Kingdom",
            }
        ],
    }
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=payload))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_returns_empty_on_http_error(client: httpx.AsyncClient) -> None:
    respx.post(_API_URL).mock(return_value=httpx.Response(403))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_returns_empty_on_empty_response(client: httpx.AsyncClient) -> None:
    respx.post(_API_URL).mock(
        return_value=httpx.Response(200, json={"total": 0, "jobPostings": []})
    )

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results == []


# ---------------------------------------------------------------------------
# max_results cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_respects_max_results(workday_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=workday_payload))

    query = JobQuery(role="Software Engineer", job_type="full-time", max_results=1)
    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(query)]

    assert len(results) == 1


# ---------------------------------------------------------------------------
# Pagination stops when total is reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_stops_pagination_when_total_exhausted(client: httpx.AsyncClient) -> None:
    page1 = {
        "total": 2,
        "jobPostings": [
            {
                "title": "Software Engineer",
                "externalPath": "/en-US/External/job/London/SE_JR1",
                "locationsText": "London, UK",
            },
            {
                "title": "Software Engineer II",
                "externalPath": "/en-US/External/job/London/SE_JR2",
                "locationsText": "London, UK",
            },
        ],
    }
    respx.post(_API_URL).mock(return_value=httpx.Response(200, json=page1))

    fetcher = WorkdayFetcher(client, _COMPANY, _TENANT, _SITE, wd=_WD)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert len(results) == 2
    assert respx.calls.call_count == 1  # only one page needed
