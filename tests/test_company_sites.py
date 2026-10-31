"""Tests for company-website search: results cache, robots.txt, careers-page discovery,
page reading, the site searcher, and the employer search with sites. HTTP mocked via
respx; the Anthropic client is mocked."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
import respx

from jobassist.Microservices.web_scraper.caching.results_cache import ResultsCache
from jobassist.Microservices.web_scraper.employers.registry import Board, board_from_url
from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery
from jobassist.Microservices.web_scraper.orchestration.employer_search import (
    EmployerSearch,
    SearchProgress,
    SearchSettings,
)
from jobassist.Microservices.web_scraper.politeness.robots import RobotsChecker
from jobassist.Microservices.web_scraper.sources.company_pages.company_site import (
    CompanySiteSearcher,
    read_page,
)
from jobassist.Microservices.web_scraper.sources.company_pages.discovery import (
    CareersPage,
    CareersPageFinder,
    _parse_answer,
)
from jobassist.Microservices.web_scraper.sources.company_pages.extractor import PageExtractor


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get_cached(self, key: str) -> str | None:
        return self.data.get(key)

    async def set_cached(self, key: str, value: str) -> None:
        self.data[key] = value


def _text_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


def _llm(*responses: MagicMock) -> anthropic.AsyncAnthropic:
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(responses))
    return client  # type: ignore[return-value]


def _posting(role: str = "Data Analyst") -> JobPosting:
    return JobPosting(
        company="Acme", role=role, location="London", url="https://acme.example/1", source="x"
    )


_QUERY = JobQuery(role="Data Analyst", job_type="full-time")


# ---------------------------------------------------------------------------
# ResultsCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_cache_reuses_saved_results() -> None:
    cache = MemoryCache()
    fetch = AsyncMock(return_value=[_posting()])
    first, hit1 = await ResultsCache(cache).get_or_fetch(["k"], fetch)
    second, hit2 = await ResultsCache(cache).get_or_fetch(["k"], fetch)
    assert (hit1, hit2) == (False, True)
    assert fetch.await_count == 1
    assert second[0].role == first[0].role


@pytest.mark.asyncio
async def test_results_cache_refresh_forces_fetch_and_resaves() -> None:
    cache = MemoryCache()
    await ResultsCache(cache).get_or_fetch(["k"], AsyncMock(return_value=[_posting("Old")]))
    fresh, hit = await ResultsCache(cache, refresh=True).get_or_fetch(
        ["k"], AsyncMock(return_value=[_posting("New")])
    )
    assert not hit and fresh[0].role == "New"
    again, hit = await ResultsCache(cache).get_or_fetch(["k"], AsyncMock())
    assert hit and again[0].role == "New"


@pytest.mark.asyncio
async def test_results_cache_expires() -> None:
    cache = MemoryCache()
    await ResultsCache(cache).get_or_fetch(["k"], AsyncMock(return_value=[_posting()]))
    (key,) = cache.data
    data = json.loads(cache.data[key])
    data["saved_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    cache.data[key] = json.dumps(data)
    fetch = AsyncMock(return_value=[])
    _, hit = await ResultsCache(cache).get_or_fetch(["k"], fetch)
    assert not hit and fetch.await_count == 1


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_robots_disallow_respected_and_fetched_once() -> None:
    route = respx.get("https://acme.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    )
    async with httpx.AsyncClient() as client:
        robots = RobotsChecker(client)
        assert await robots.allowed("https://acme.example/careers")
        assert not await robots.allowed("https://acme.example/private/jobs")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_robots_missing_allows_and_server_error_disallows() -> None:
    respx.get("https://a.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://b.example/robots.txt").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        robots = RobotsChecker(client)
        assert await robots.allowed("https://a.example/jobs")
        assert not await robots.allowed("https://b.example/jobs")


# ---------------------------------------------------------------------------
# Careers-page discovery
# ---------------------------------------------------------------------------


_FOUND = json.dumps(
    {
        "found": True,
        "listing_url": "https://careers.acme.example/jobs",
        "search_url_template": "https://careers.acme.example/jobs?q={query}",
        "notes": "Uses Workday",
    }
)


def test_parse_answer_takes_final_json_and_validates() -> None:
    page = _parse_answer("I searched and found it.\n```json\n" + _FOUND + "\n```")
    assert page is not None
    assert page.url_for("Data Analyst") == "https://careers.acme.example/jobs?q=Data+Analyst"
    assert page.is_search()
    assert _parse_answer('{"found": false}') is None
    assert _parse_answer('{"found": true, "listing_url": "careers.acme.example"}') is None
    assert _parse_answer("no json here") is None


_NOT_FOUND = '{"found": false}'


@pytest.mark.asyncio
async def test_finder_uses_cheap_guess_first_and_caches() -> None:
    llm = _llm(_text_response(_FOUND))
    cache = MemoryCache()
    first = await CareersPageFinder(llm, cache).find("Acme")
    second = await CareersPageFinder(llm, cache).find("Acme (UK office)")  # same normalised name
    assert first == second and first is not None
    assert llm.messages.create.await_count == 1  # type: ignore[attr-defined]
    # The first, cheap call has no web search tool.
    assert "tools" not in llm.messages.create.call_args.kwargs  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_finder_falls_back_to_web_search_when_guess_fails_check() -> None:
    respx.get("https://careers.acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://careers.acme.example/jobs").mock(return_value=httpx.Response(404))
    llm = _llm(_text_response(_FOUND), _text_response(_FOUND))
    async with httpx.AsyncClient() as client:
        finder = CareersPageFinder(llm, MemoryCache(), http=client, robots=RobotsChecker(client))
        page = await finder.find("Acme")
    assert page is not None
    calls = llm.messages.create.await_args_list  # type: ignore[attr-defined]
    assert len(calls) == 2
    assert calls[1].kwargs["tools"][0]["type"] == "web_search_20260209"
    assert calls[1].kwargs["tools"][0]["max_uses"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_finder_accepts_guess_that_looks_like_jobs_page() -> None:
    respx.get("https://careers.acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://careers.acme.example/jobs").mock(
        return_value=httpx.Response(200, text="Open positions — search jobs and apply. Careers.")
    )
    llm = _llm(_text_response(_FOUND))
    async with httpx.AsyncClient() as client:
        finder = CareersPageFinder(llm, MemoryCache(), http=client, robots=RobotsChecker(client))
        assert await finder.find("Acme") is not None
    assert llm.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_finder_resumes_paused_search() -> None:
    llm = _llm(
        _text_response(_NOT_FOUND),
        _text_response("", stop_reason="pause_turn"),
        _text_response(_FOUND),
    )
    page = await CareersPageFinder(llm, MemoryCache()).find("Acme")
    assert page is not None
    third_call = llm.messages.create.await_args_list[2].kwargs  # type: ignore[attr-defined]
    assert third_call["messages"][-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_finder_caches_not_found_but_not_api_errors() -> None:
    cache = MemoryCache()
    llm = _llm(_text_response(_NOT_FOUND), _text_response(_NOT_FOUND))
    assert await CareersPageFinder(llm, cache).find("Nowhere Ltd") is None
    assert await CareersPageFinder(llm, cache).find("Nowhere Ltd") is None
    assert llm.messages.create.await_count == 2  # guess + search, once; then cached
    assert await CareersPageFinder(llm, cache).is_cached("Nowhere Ltd")

    failing = MagicMock(spec=anthropic.AsyncAnthropic)
    failing.messages = MagicMock()
    failing.messages.create = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    )
    empty = MemoryCache()
    assert await CareersPageFinder(failing, empty).find("Acme") is None
    assert empty.data == {}


# ---------------------------------------------------------------------------
# Page reading + board detection
# ---------------------------------------------------------------------------


_LISTING_HTML = """
<html><head><script>var x = 1;</script></head><body>
<nav>Home</nav>
<h1>Open roles at Acme</h1>
<ul>
  <li><a href="/jobs/101">Data Analyst</a> — London</li>
  <li><a href="/jobs/102">Senior Data Analyst</a> — Leeds</li>
  <li><a href="/jobs/103">Office Manager</a> — London</li>
  <li><a href="mailto:jobs@acme.example">Email us</a></li>
</ul>
<p>""" + ("We are a friendly company. " * 30) + """</p>
<footer>© Acme</footer>
</body></html>
"""


def test_read_page_text_and_absolute_links() -> None:
    content = read_page(_LISTING_HTML, "https://acme.example/careers")
    assert "Open roles at Acme" in content.text
    assert "var x" not in content.text and "© Acme" not in content.text
    assert content.links["https://acme.example/jobs/101"] == "Data Analyst"
    assert not any(url.startswith("mailto:") for url in content.links)
    assert "Data Analyst -> https://acme.example/jobs/101" in content.for_extraction()


def test_board_found_in_page_html_skips_route_segments() -> None:
    html = (
        '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
        '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe>'
    )
    assert board_from_url(html) == Board("greenhouse", "acme")


# ---------------------------------------------------------------------------
# CompanySiteSearcher
# ---------------------------------------------------------------------------


_EXTRACTED = json.dumps(
    {
        "postings": [
            {"role": "Data Analyst", "location": "London", "url": "https://acme.example/jobs/101"},
            {"role": "Senior Data Analyst", "location": "Leeds",
             "url": "https://acme.example/jobs/invented-999"},
            {"role": "Office Manager", "location": "London", "url": "https://acme.example/jobs/103"},
        ]
    }
)


def _searcher(client: httpx.AsyncClient, llm: anthropic.AsyncAnthropic) -> CompanySiteSearcher:
    return CompanySiteSearcher(
        client, PageExtractor(llm, MemoryCache()), RobotsChecker(client), use_browser=False
    )


@pytest.mark.asyncio
@respx.mock
async def test_site_search_extracts_filters_and_checks_urls() -> None:
    respx.get("https://acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://acme.example/careers").mock(
        return_value=httpx.Response(200, text=_LISTING_HTML)
    )
    llm = _llm(_text_response(_EXTRACTED))
    async with httpx.AsyncClient() as client:
        outcome = await _searcher(client, llm).search(
            "Acme", CareersPage(listing_url="https://acme.example/careers"), _QUERY
        )

    assert [(p.role, p.url) for p in outcome.postings] == [
        ("Data Analyst", "https://acme.example/jobs/101"),
        # A URL that isn't on the page is replaced by the page itself, never trusted.
        ("Senior Data Analyst", "https://acme.example/careers"),
    ]
    assert all(p.source == "company_page" and p.company == "Acme" for p in outcome.postings)
    sent = llm.messages.create.call_args.kwargs["messages"][0]["content"]  # type: ignore[attr-defined]
    assert "LINKS (link text -> URL)" in sent


@pytest.mark.asyncio
@respx.mock
async def test_site_search_returns_embedded_board_without_llm() -> None:
    respx.get("https://acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://acme.example/careers").mock(
        return_value=httpx.Response(
            200, text='<a href="https://jobs.lever.co/acme">See all jobs</a>'
        )
    )
    llm = _llm()
    async with httpx.AsyncClient() as client:
        outcome = await _searcher(client, llm).search(
            "Acme", CareersPage(listing_url="https://acme.example/careers"), _QUERY
        )
    assert outcome.board == Board("lever", "acme")
    assert llm.messages.create.await_count == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_site_search_respects_robots() -> None:
    respx.get("https://acme.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    page_route = respx.get("https://acme.example/careers")
    async with httpx.AsyncClient() as client:
        outcome = await _searcher(client, _llm()).search(
            "Acme", CareersPage(listing_url="https://acme.example/careers"), _QUERY
        )
    assert outcome.postings == [] and "robots.txt" in outcome.note
    assert page_route.call_count == 0


# ---------------------------------------------------------------------------
# EmployerSearch with company websites
# ---------------------------------------------------------------------------


def _site_routes() -> Any:
    respx.get("https://acme.example/robots.txt").mock(return_value=httpx.Response(404))
    return respx.get("https://acme.example/careers").mock(
        return_value=httpx.Response(200, text=_LISTING_HTML)
    )


@pytest.mark.asyncio
@respx.mock
async def test_employer_search_uses_site_and_reuses_saved_results() -> None:
    page = _site_routes()
    query = JobQuery(
        role="Data Analyst",
        job_type="full-time",
        location="London",
        companies=["Acme"],
        company_urls={"Acme": "https://acme.example/careers"},
    )
    cache = MemoryCache()
    llm = _llm(_text_response(_EXTRACTED))
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=llm, company_sites=True)
        progress = SearchProgress()
        search = EmployerSearch(client, cache, settings, progress)
        postings, statuses = await search.search_companies(query, [query.role])
        # Second run: served from saved results, no page fetch.
        again, _ = await EmployerSearch(client, cache, settings).search_companies(
            query, [query.role]
        )

    # "Senior Data Analyst" is in Leeds, so the London filter drops it.
    assert [p.role for p in postings] == ["Data Analyst"]
    assert statuses[0].found == {"company_page": 1}
    assert "website searched" in statuses[0].notes
    assert (progress.done, progress.total) == (1, 1)
    assert [p.role for p in again] == ["Data Analyst"]
    assert page.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_employer_search_refresh_fetches_again() -> None:
    page = _site_routes()
    query = JobQuery(
        role="Data Analyst",
        job_type="full-time",
        companies=["Acme"],
        company_urls={"Acme": "https://acme.example/careers"},
    )
    cache = MemoryCache()
    async with httpx.AsyncClient() as client:
        llm = _llm(_text_response(_EXTRACTED))
        await EmployerSearch(
            client, cache, SearchSettings(llm=llm, company_sites=True)
        ).search_companies(query, [query.role])
        await EmployerSearch(
            client, cache, SearchSettings(llm=llm, company_sites=True, refresh=True)
        ).search_companies(query, [query.role])
    assert page.call_count == 2
    # Same page content: the LLM extraction itself is cached by content hash.
    assert llm.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_employer_search_sites_without_llm_explains() -> None:
    query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Nowhere Ltd"])
    async with httpx.AsyncClient() as client:
        _, statuses = await EmployerSearch(
            client, MemoryCache(), SearchSettings(company_sites=True)
        ).search_companies(query, [query.role])
    assert statuses[0].notes == ["website search needs the Anthropic API key"]
