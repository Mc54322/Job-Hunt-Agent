"""Tests for the LLM page extractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from jobassist.extractor import PageExtractor, _resolve_url, _strip_fences
from jobassist.schemas import JobPosting
from jobassist.store import Store

_COMPANY = "Acme"
_PAGE_URL = "https://careers.acme.com/jobs"

_POSTINGS_RESPONSE = json.dumps({
    "postings": [
        {
            "role": "Software Engineer",
            "location": "London, UK",
            "url": "https://careers.acme.com/jobs/se-001",
            "salary_raw": "£60,000 - £80,000",
            "description": "Build distributed systems.",
        },
        {
            "role": "Data Analyst",
            "location": "Remote",
            "url": "/jobs/da-002",
            "salary_raw": None,
            "description": None,
        },
    ]
})

_EMPTY_RESPONSE = json.dumps({"postings": []})


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def _make_client(text: str) -> anthropic.AsyncAnthropic:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    messages = MagicMock()
    messages.create = AsyncMock(return_value=response)
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = messages
    return client  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_resolve_url_absolute_unchanged() -> None:
    assert _resolve_url("https://example.com/jobs/1", "https://base.com") == "https://example.com/jobs/1"


def test_resolve_url_relative_prepends_base() -> None:
    result = _resolve_url("/jobs/1", "https://careers.acme.com/jobs")
    assert result == "https://careers.acme.com/jobs/1"


def test_strip_fences_removes_json_fence() -> None:
    text = '```json\n{"postings": []}\n```'
    assert _strip_fences(text) == '{"postings": []}'


def test_strip_fences_leaves_plain_json() -> None:
    text = '{"postings": []}'
    assert _strip_fences(text) == text


# ---------------------------------------------------------------------------
# PageExtractor — cache miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_calls_llm_on_cache_miss(store: Store) -> None:
    client = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client, store)

    results = await extractor.extract(_COMPANY, _PAGE_URL, "some page text")

    client.messages.create.assert_awaited_once()  # type: ignore[attr-defined]
    assert len(results) == 2
    assert all(isinstance(p, JobPosting) for p in results)


@pytest.mark.asyncio
async def test_extract_returns_correct_fields(store: Store) -> None:
    client = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client, store)

    results = await extractor.extract(_COMPANY, _PAGE_URL, "some page text")

    first = results[0]
    assert first.company == _COMPANY
    assert first.role == "Software Engineer"
    assert first.location == "London, UK"
    assert first.source == "company_page"
    assert first.salary_raw == "£60,000 - £80,000"


@pytest.mark.asyncio
async def test_extract_resolves_relative_url(store: Store) -> None:
    client = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client, store)

    results = await extractor.extract(_COMPANY, _PAGE_URL, "some page text")

    # Second posting has a relative URL "/jobs/da-002"
    assert results[1].url.startswith("https://")
    assert "da-002" in results[1].url


@pytest.mark.asyncio
async def test_extract_caches_response(store: Store) -> None:
    client = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client, store)
    text = "page text content"

    await extractor.extract(_COMPANY, _PAGE_URL, text)
    await extractor.extract(_COMPANY, _PAGE_URL, text)

    assert client.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_extract_returns_cached_result(store: Store) -> None:
    client = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client, store)
    text = "page text content"

    first = await extractor.extract(_COMPANY, _PAGE_URL, text)
    second = await extractor.extract(_COMPANY, _PAGE_URL, text)

    assert len(first) == len(second)
    assert first[0].role == second[0].role


# ---------------------------------------------------------------------------
# PageExtractor — empty / error responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_returns_empty_when_no_postings(store: Store) -> None:
    client = _make_client(_EMPTY_RESPONSE)
    extractor = PageExtractor(client, store)

    results = await extractor.extract(_COMPANY, _PAGE_URL, "page with no jobs")

    assert results == []


@pytest.mark.asyncio
async def test_extract_handles_invalid_json_gracefully(store: Store) -> None:
    client = _make_client("not valid json at all")
    extractor = PageExtractor(client, store)

    results = await extractor.extract(_COMPANY, _PAGE_URL, "some text")

    assert results == []


@pytest.mark.asyncio
async def test_extract_handles_schema_mismatch_gracefully(store: Store) -> None:
    client = _make_client('{"unexpected": "structure"}')
    extractor = PageExtractor(client, store)

    # Should return empty list (ValidationError caught internally)
    results = await extractor.extract(_COMPANY, _PAGE_URL, "some text")

    assert results == []


# ---------------------------------------------------------------------------
# CompanyPageFetcher wired with extractor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_page_fetcher_with_extractor_yields_postings(store: Store) -> None:
    import httpx
    import respx

    from jobassist.schemas import JobQuery
    from jobassist.sources.company_page import CompanyPageFetcher
    from tests.test_company_page import _RICH_HTML

    client_llm = _make_client(_POSTINGS_RESPONSE)
    extractor = PageExtractor(client_llm, store)

    with respx.mock:
        respx.get(_PAGE_URL).mock(return_value=httpx.Response(200, text=_RICH_HTML))
        http = httpx.AsyncClient()
        fetcher = CompanyPageFetcher(
            http, _COMPANY, _PAGE_URL, extractor=extractor, use_playwright=False
        )
        query = JobQuery(role="Software Engineer", job_type="full-time")
        results = [p async for p in await fetcher.search(query)]

    assert len(results) > 0
    assert all(p.source == "company_page" for p in results)


@pytest.mark.asyncio
async def test_company_page_fetcher_without_extractor_yields_nothing(store: Store) -> None:
    import httpx

    from jobassist.schemas import JobQuery
    from jobassist.sources.company_page import CompanyPageFetcher

    http = httpx.AsyncClient()
    fetcher = CompanyPageFetcher(http, _COMPANY, _PAGE_URL, use_playwright=False)
    query = JobQuery(role="Engineer", job_type="full-time")
    results = [p async for p in await fetcher.search(query)]

    assert results == []
