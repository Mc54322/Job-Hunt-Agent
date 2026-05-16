"""Tests for the generic company-page fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from jobassist.schemas import JobQuery
from jobassist.sources.company_page import (
    _MIN_CONTENT_CHARS,
    CompanyPageFetcher,
    _extract,
    fetch_content,
)

_CAREERS_URL = "https://careers.acme.com/jobs"
_COMPANY = "Acme"

_RICH_HTML = """\
<html><body>
<h1>Careers at Acme</h1>
<p>We are hiring talented engineers to help us build the future of technology.
Our team works on exciting distributed systems problems at global scale.
Join us to work with brilliant colleagues on challenging and impactful problems.
We offer competitive salaries, remote-friendly work, and excellent benefits.
Open roles include: Software Engineer, Data Engineer, Product Manager.</p>
</body></html>
"""

_THIN_HTML = "<html><body><div id='app'></div></body></html>"


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


# ---------------------------------------------------------------------------
# _extract helper
# ---------------------------------------------------------------------------


def test_extract_returns_text_from_html() -> None:
    result = _extract(_RICH_HTML)
    assert "Software Engineer" in result
    assert len(result) > 0


def test_extract_returns_empty_for_empty_html() -> None:
    assert _extract("") == ""


def test_extract_returns_empty_for_thin_html() -> None:
    # A page with only a JS mount point yields no extractable content
    result = _extract(_THIN_HTML)
    assert result == "" or len(result) < _MIN_CONTENT_CHARS


# ---------------------------------------------------------------------------
# fetch_content — httpx path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_fetch_content_returns_extracted_text(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(200, text=_RICH_HTML))

    text = await fetch_content(_CAREERS_URL, client, use_playwright=False)
    assert len(text) > 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_content_returns_empty_on_http_error(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(404))

    text = await fetch_content(_CAREERS_URL, client, use_playwright=False)
    assert text == ""


@pytest.mark.asyncio
@respx.mock
async def test_fetch_content_returns_empty_on_network_error(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(side_effect=httpx.ConnectError("refused"))

    text = await fetch_content(_CAREERS_URL, client, use_playwright=False)
    assert text == ""


# ---------------------------------------------------------------------------
# fetch_content — Playwright fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_playwright_not_called_when_httpx_succeeds(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(200, text=_RICH_HTML))

    with patch(
        "jobassist.sources.company_page._fetch_html_playwright", new_callable=AsyncMock
    ) as mock_pw:
        await fetch_content(_CAREERS_URL, client, use_playwright=True)

    mock_pw.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_playwright_called_when_httpx_yields_thin_content(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(200, text=_THIN_HTML))

    with (
        patch("jobassist.sources.company_page._PLAYWRIGHT_AVAILABLE", True),
        patch(
            "jobassist.sources.company_page._fetch_html_playwright",
            new_callable=AsyncMock,
            return_value=_RICH_HTML,
        ) as mock_pw,
    ):
        text = await fetch_content(_CAREERS_URL, client, use_playwright=True)

    mock_pw.assert_called_once_with(_CAREERS_URL)
    assert len(text) > 0


@pytest.mark.asyncio
@respx.mock
async def test_playwright_not_called_when_disabled(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(200, text=_THIN_HTML))

    with patch(
        "jobassist.sources.company_page._fetch_html_playwright", new_callable=AsyncMock
    ) as mock_pw:
        await fetch_content(_CAREERS_URL, client, use_playwright=False)

    mock_pw.assert_not_called()


# ---------------------------------------------------------------------------
# CompanyPageFetcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_company_fetcher_fetch_content(client: httpx.AsyncClient) -> None:
    respx.get(_CAREERS_URL).mock(return_value=httpx.Response(200, text=_RICH_HTML))

    fetcher = CompanyPageFetcher(client, _COMPANY, _CAREERS_URL, use_playwright=False)
    text = await fetcher.fetch_content()
    assert len(text) > 0


@pytest.mark.asyncio
async def test_company_fetcher_search_yields_nothing(client: httpx.AsyncClient) -> None:
    fetcher = CompanyPageFetcher(client, _COMPANY, _CAREERS_URL, use_playwright=False)
    query = JobQuery(role="Engineer", job_type="full-time")
    results = [p async for p in await fetcher.search(query)]
    assert results == []
