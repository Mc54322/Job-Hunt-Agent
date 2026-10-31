"""Company careers-site search — fetch a company's own job listing page and extract jobs.

For one company and its `CareersPage`:

1. Respect robots.txt.
2. Fetch the page (keyword search results when the site's search URL is known);
   render it in a headless browser when plain HTTP returns a JavaScript shell.
3. If the page embeds or links to a known ATS board, hand back that `Board` — its
   JSON feed is cheaper and more accurate than scraping (ATS JSON never goes to the LLM).
4. Otherwise send the page text plus its links to the LLM extractor and keep only
   postings whose title matches the role (or an alias); a URL that does not appear on
   the page is replaced by the page URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin

import httpx
from selectolax.parser import HTMLParser

from jobassist.Microservices.web_scraper.employers.registry import Board, board_from_url
from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery
from jobassist.Microservices.web_scraper.politeness.robots import RobotsChecker
from jobassist.Microservices.web_scraper.sources.company_pages.company_page import _Extractor
from jobassist.Microservices.web_scraper.sources.company_pages.discovery import CareersPage

_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_STRIP_TAGS = ("script", "style", "noscript", "svg", "template", "iframe", "footer")
_MAX_TEXT_CHARS = 30_000
_MAX_LINKS = 400
# Below these a page is treated as a JavaScript shell and rendered in a browser.
_MIN_TEXT_CHARS = 400
_MIN_LINKS = 8
_RENDER_SETTLE_MS = 4_000
# Cost control: long pages are cut down to the lines around a matching title.
_FOCUS_THRESHOLD = 6_000
_HEAD_CHARS = 1_500
_CONTEXT_LINES = 3
_MAX_FOCUSED_CHARS = 15_000
_MAX_TITLE_LINKS = 120
_MAX_JOB_LINKS = 40
_JOB_URL = re.compile(r"job|vacanc|position|opening|requisition|career|role", re.I)

try:
    from playwright.async_api import async_playwright as _async_playwright

    _BROWSER_AVAILABLE = True
except ImportError:  # pragma: no cover - playwright is a project dependency
    _BROWSER_AVAILABLE = False


@dataclass
class SiteSearchOutcome:
    """What searching one company's site produced."""

    postings: list[JobPosting] = field(default_factory=list)
    board: Board | None = None  # set when the site turned out to be an ATS board
    note: str = ""
    page_url: str | None = None


@dataclass
class PageContent:
    """Readable text and absolute links from one HTML page."""

    text: str
    links: dict[str, str]  # absolute URL -> link text

    def is_thin(self) -> bool:
        return len(self.text) < _MIN_TEXT_CHARS or len(self.links) < _MIN_LINKS

    def for_extraction(self) -> str:
        link_lines = "\n".join(f"{label} -> {url}" for url, label in self.links.items())
        return f"{self.text}\n\nLINKS (link text -> URL):\n{link_lines}"


def read_page(html: str, base_url: str) -> PageContent:
    """Return the visible text and links of *html* (resolved against *base_url*)."""
    tree = HTMLParser(html)
    tree.strip_tags(list(_STRIP_TAGS))
    body = tree.body or tree.root
    text = body.text(separator="\n") if body is not None else ""
    text = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()

    links: dict[str, str] = {}
    for anchor in tree.css("a[href]"):
        href = (anchor.attributes.get("href") or "").strip()
        label = " ".join(anchor.text(separator=" ").split())
        if not href or not label or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(base_url, href)).url
        links.setdefault(url, label[:120])
        if len(links) >= _MAX_LINKS:
            break
    return PageContent(text=text[:_MAX_TEXT_CHARS], links=links)


def focus_for_roles(content: PageContent, terms: list[str]) -> str | None:
    """The parts of *content* worth sending to Claude for *terms*, or None if none match.

    A page that never mentions the role (or an alias) can't list a matching job, so it
    costs nothing. Long pages keep their opening plus the lines around each mention;
    links keep those whose text matches a term, then other job-looking links.
    """
    wanted = [t.lower() for t in terms if t.strip()]

    def mentions(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in wanted)

    title_links = {url: label for url, label in content.links.items() if mentions(label)}
    if not title_links and not mentions(content.text):
        return None

    if len(content.text) <= _FOCUS_THRESHOLD:
        text = content.text
    else:
        lines = content.text.splitlines()
        keep: set[int] = set()
        for i, line in enumerate(lines):
            if mentions(line):
                start, stop = i - _CONTEXT_LINES, i + _CONTEXT_LINES + 1
                keep.update(range(max(0, start), min(len(lines), stop)))
        excerpt = "\n".join(lines[i] for i in sorted(keep))
        text = (content.text[:_HEAD_CHARS] + "\n…\n" + excerpt)[:_MAX_FOCUSED_CHARS]

    job_links = [
        (url, label) for url, label in content.links.items()
        if url not in title_links and _JOB_URL.search(url)
    ]
    links = list(title_links.items())[:_MAX_TITLE_LINKS] + job_links[:_MAX_JOB_LINKS]
    link_lines = "\n".join(f"{label} -> {url}" for url, label in links)
    return f"{text}\n\nLINKS (link text -> URL):\n{link_lines}"


def _title_matches(title: str, terms: list[str]) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in terms)


class CompanySiteSearcher:
    """Search companies' own careers pages for postings matching a query."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        extractor: _Extractor,
        robots: RobotsChecker,
        *,
        use_browser: bool = True,
    ) -> None:
        self._client = client
        self._extractor = extractor
        self._robots = robots
        self._use_browser = use_browser and _BROWSER_AVAILABLE

    async def search(self, company: str, page: CareersPage, query: JobQuery) -> SiteSearchOutcome:
        """Search *company*'s careers *page* for jobs matching *query*."""
        url = page.url_for(query.role)
        board = board_from_url(url)
        if board is not None:
            return SiteSearchOutcome(board=board, page_url=url, note="site uses a jobs board")
        if not await self._robots.allowed(url):
            return SiteSearchOutcome(
                page_url=url, note="website asks automated tools not to visit (robots.txt)"
            )

        html, final_url = await self._fetch(url)
        board = board_from_url(final_url) or (board_from_url(html) if html else None)
        if board is not None:
            return SiteSearchOutcome(board=board, page_url=url, note="site uses a jobs board")

        content = read_page(html, final_url) if html else PageContent("", {})
        if content.is_thin() and self._use_browser:
            rendered = await self._render(url)
            if rendered:
                board = board_from_url(rendered)
                if board is not None:
                    return SiteSearchOutcome(
                        board=board, page_url=url, note="site uses a jobs board"
                    )
                rendered_content = read_page(rendered, final_url)
                if len(rendered_content.text) > len(content.text):
                    content = rendered_content
        if not content.text:
            return SiteSearchOutcome(page_url=url, note="website could not be read")

        terms = query.role_terms()
        focused = focus_for_roles(content, terms)
        if focused is None:
            return SiteSearchOutcome(
                page_url=url, note="website searched — no matching jobs listed"
            )
        extracted = await self._extractor.extract(company, final_url, focused, terms)
        postings: list[JobPosting] = []
        for posting in extracted:
            # Even keyword-search pages: many sites ignore the keyword and list everything.
            if not _title_matches(posting.role, terms):
                continue
            # Only trust URLs that are really on the page; otherwise point at the page.
            if posting.url not in content.links:
                posting = posting.model_copy(update={"url": final_url})
            postings.append(posting)
        note = "website searched" if postings else "website searched — no matching jobs listed"
        return SiteSearchOutcome(postings=postings, page_url=url, note=note)

    async def _fetch(self, url: str) -> tuple[str, str]:
        """Return ``(html, final_url)`` via plain HTTP; empty html on failure."""
        try:
            resp = await self._client.get(
                url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return "", url
        return resp.text, str(resp.url)

    async def _render(self, url: str) -> str:
        """Return the page HTML after JavaScript has run, or empty on failure."""
        try:
            async with _async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    tab = await browser.new_page(user_agent=_USER_AGENT)
                    await tab.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await tab.wait_for_timeout(_RENDER_SETTLE_MS)
                    html: Any = await tab.content()
                    return str(html)
                finally:
                    await browser.close()
        except Exception:  # noqa: BLE001 - browser missing, timeout, crash: skip rendering
            return ""
