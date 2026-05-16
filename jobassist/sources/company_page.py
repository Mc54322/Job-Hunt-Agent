"""Generic company-page fetcher — httpx + trafilatura with optional Playwright fallback."""

from __future__ import annotations

from typing import AsyncIterator

import httpx
import trafilatura

from jobassist.schemas import JobPosting, JobQuery

_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_MIN_CONTENT_CHARS = 200

try:
    from playwright.async_api import (  # type: ignore[import-not-found]
        async_playwright as _async_playwright,
    )

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


async def fetch_content(
    url: str,
    client: httpx.AsyncClient,
    *,
    use_playwright: bool = True,
) -> str:
    """Fetch and extract main text from *url*.

    Tries a plain HTTP GET first.  If ``trafilatura`` returns less than
    ``_MIN_CONTENT_CHARS`` characters (indicating a JS-rendered page), falls
    back to Playwright when *use_playwright* is ``True`` and Playwright is
    installed.  Returns the extracted text, or an empty string on failure.
    """
    raw_html = await _fetch_html_httpx(url, client)
    content = _extract(raw_html) if raw_html else ""

    if len(content) >= _MIN_CONTENT_CHARS:
        return content

    if use_playwright and _PLAYWRIGHT_AVAILABLE:
        rendered = await _fetch_html_playwright(url)
        if rendered:
            content = _extract(rendered) or content

    return content


async def _fetch_html_httpx(url: str, client: httpx.AsyncClient) -> str:
    """Return raw HTML from *url* via httpx, or empty string on error."""
    try:
        resp = await client.get(url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        return ""


async def _fetch_html_playwright(url: str) -> str:
    """Return rendered HTML from *url* using a headless browser."""
    try:
        async with _async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_USER_AGENT)
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            html: str = await page.content()
            await browser.close()
            return html
    except Exception:  # noqa: BLE001
        return ""


def _extract(html: str) -> str:
    """Run trafilatura main-content extraction; return empty string if nothing found."""
    result: str | None = trafilatura.extract(html, include_comments=False, include_tables=False)
    return result or ""


class CompanyPageFetcher:
    """Fetches raw text from a company careers page for later LLM extraction.

    The ``search`` method yields nothing until an LLM extractor is wired in
    (Task 13).  Use ``fetch_content`` directly to obtain the page text.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        company: str,
        careers_url: str,
        *,
        use_playwright: bool = True,
    ) -> None:
        self._client = client
        self._company = company
        self._careers_url = careers_url
        self._use_playwright = use_playwright

    async def fetch_content(self) -> str:
        """Fetch and return extracted text from the careers page."""
        return await fetch_content(
            self._careers_url,
            self._client,
            use_playwright=self._use_playwright,
        )

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Stub — yields nothing until the LLM extractor (Task 13) is wired in."""

        async def _empty() -> AsyncIterator[JobPosting]:
            return
            yield  # noqa: F701 — makes this an async generator

        return _empty()
