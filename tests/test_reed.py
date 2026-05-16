"""Tests for the Reed UK job board fetcher."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from jobassist.schemas import JobPosting, JobQuery
from jobassist.sources.reed import ReedFetcher, _auth_header, _format_salary, _parse_date

_FIXTURES = Path(__file__).parent / "fixtures"
_SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
_API_KEY = "test-api-key-12345"

_QUERY = JobQuery(
    role="Software Engineer",
    job_type="full-time",
    location="London",
    max_results=50,
)


@pytest.fixture
def reed_payload() -> dict:  # type: ignore[type-arg]
    return json.loads((_FIXTURES / "reed_search.json").read_text())


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_auth_header_is_basic_base64() -> None:
    header = _auth_header("mykey")
    assert header.startswith("Basic ")
    import base64

    decoded = base64.b64decode(header[6:]).decode()
    assert decoded == "mykey:"


def test_format_salary_both_bounds() -> None:
    assert _format_salary(50000, 70000) == "£50,000 - £70,000"


def test_format_salary_min_only() -> None:
    assert _format_salary(60000, None) == "£60,000+"


def test_format_salary_max_only() -> None:
    assert _format_salary(None, 80000) == "up to £80,000"


def test_format_salary_both_none() -> None:
    assert _format_salary(None, None) is None


def test_parse_date_dd_mm_yyyy() -> None:
    d = _parse_date("15/01/2025")
    assert d is not None
    assert d.year == 2025
    assert d.month == 1
    assert d.day == 15


def test_parse_date_none_input() -> None:
    assert _parse_date(None) is None


def test_parse_date_invalid_returns_none() -> None:
    assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Basic fetching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_returns_postings(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert len(results) == 3
    assert all(isinstance(p, JobPosting) for p in results)


@pytest.mark.asyncio
@respx.mock
async def test_posting_fields_are_correct(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    first = results[0]
    assert first.company == "Acme Corp"
    assert first.role == "Software Engineer"
    assert first.location == "London"
    assert first.source == "reed"
    assert "reed.co.uk" in first.url


@pytest.mark.asyncio
@respx.mock
async def test_salary_is_formatted(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results[0].salary_raw == "£50,000 - £70,000"


@pytest.mark.asyncio
@respx.mock
async def test_null_salary_becomes_none(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results[1].salary_raw is None


@pytest.mark.asyncio
@respx.mock
async def test_min_only_salary(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results[2].salary_raw == "£60,000+"


@pytest.mark.asyncio
@respx.mock
async def test_description_is_populated(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results[0].description is not None
    assert "Software Engineer" in results[0].description


@pytest.mark.asyncio
@respx.mock
async def test_auth_header_sent(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    route = respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    fetcher = ReedFetcher(client, _API_KEY)
    await fetcher.search(_QUERY)  # consume the iterator
    async for _ in await fetcher.search(_QUERY):
        break

    sent_headers = route.calls[0].request.headers
    assert "authorization" in sent_headers
    assert sent_headers["authorization"].startswith("Basic ")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_returns_empty_on_401(client: httpx.AsyncClient) -> None:
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(401))

    fetcher = ReedFetcher(client, "bad-key")
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_returns_empty_on_empty_results(client: httpx.AsyncClient) -> None:
    respx.get(_SEARCH_URL).mock(
        return_value=httpx.Response(200, json={"totalResults": 0, "results": []})
    )

    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert results == []


# ---------------------------------------------------------------------------
# max_results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_respects_max_results(reed_payload: dict, client: httpx.AsyncClient) -> None:  # type: ignore[type-arg]
    respx.get(_SEARCH_URL).mock(return_value=httpx.Response(200, json=reed_payload))

    query = JobQuery(role="Software Engineer", job_type="full-time", max_results=1)
    fetcher = ReedFetcher(client, _API_KEY)
    results = [p async for p in await fetcher.search(query)]

    assert len(results) == 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_paginates_when_more_results_available(client: httpx.AsyncClient) -> None:
    page1 = {
        "totalResults": 4,
        "results": [
            {
                "jobId": i,
                "employerName": f"Co{i}",
                "jobTitle": "Software Engineer",
                "locationName": "London",
                "minimumSalary": None,
                "maximumSalary": None,
                "date": "15/01/2025",
                "jobUrl": f"https://www.reed.co.uk/jobs/se/{i}",
                "jobDescription": "desc",
            }
            for i in range(1, 3)
        ],
    }
    page2 = {
        "totalResults": 4,
        "results": [
            {
                "jobId": i,
                "employerName": f"Co{i}",
                "jobTitle": "Software Engineer",
                "locationName": "London",
                "minimumSalary": None,
                "maximumSalary": None,
                "date": "15/01/2025",
                "jobUrl": f"https://www.reed.co.uk/jobs/se/{i}",
                "jobDescription": "desc",
            }
            for i in range(3, 5)
        ],
    }
    respx.get(_SEARCH_URL).mock(side_effect=[
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ])

    fetcher = ReedFetcher(client, _API_KEY, results_per_page=2)
    results = [p async for p in await fetcher.search(_QUERY)]

    assert len(results) == 4
