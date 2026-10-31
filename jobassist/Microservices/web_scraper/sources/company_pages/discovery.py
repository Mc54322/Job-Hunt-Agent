"""Careers-page finder — locates a company's official job-listing page.

Cheapest first: Claude names the URL from what it knows (a tiny call), and a free HTTP
fetch confirms it really is a jobs page. Only when that fails does it fall back to
Claude with the server-side web search tool (the expensive step: search results are
fed back as input). Results are cached per company for 30 days
(careers sites rarely move); "not found" is cached for 7 days so a company with no
findable site does not cost a web search on every run. A careers URL from the user's
employer sheet skips discovery entirely.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import anthropic
import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from jobassist.Microservices.web_scraper.cache_client import CacheClient, cache_key
from jobassist.Microservices.web_scraper.costs.meter import CallFailed, CostMeter, metered_create
from jobassist.Microservices.web_scraper.employers.registry import (
    board_from_url,
    normalise_company,
)
from jobassist.Microservices.web_scraper.politeness.robots import RobotsChecker

_MODEL = "claude-sonnet-4-6"
_FOUND_MAX_AGE = timedelta(days=30)
_NOT_FOUND_MAX_AGE = timedelta(days=7)
_MAX_CONTINUATIONS = 2  # server-side search loops may pause; resume at most this often
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
# Words a real job-listing page uses; a verified page must contain several.
_JOBS_PAGE_WORDS = ("job", "vacanc", "career", "position", "opening", "apply", "role")
_MIN_JOBS_WORDS = 3

_WEB_SEARCH_TOOL: anthropic.types.WebSearchTool20260209Param = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 2,
    "user_location": {"type": "approximate", "country": "GB"},
}

_SYSTEM_PROMPT = """\
You find the official page where a company lists its open jobs, for a UK job seeker.

Search the web, then reply with only a JSON object (no markdown fences):
{
  "found": true or false,
  "listing_url": "URL of the page that lists open jobs (a job search/results page, not a \
general 'life at company' page), or null",
  "search_url_template": "the same job search page with the keyword replaced by {query}, \
e.g. https://careers.example.com/jobs?q={query} — or null if you have not seen the site's \
keyword URL format",
  "notes": "one short sentence, e.g. which jobs platform the site uses"
}

Rules:
- Use only URLs that appear in your search results. Never construct or guess a URL.
- Prefer the company's own careers site or its jobs platform (Workday, Greenhouse, Lever, \
Ashby, SmartRecruiters, Workable, Oracle, SuccessFactors, Eightfold, etc.) over job boards \
such as LinkedIn, Indeed, Glassdoor or Reed.
- Prefer the UK or global listing if the company has several.
- If you cannot find an official job listing page, return found=false."""


_GUESS_PROMPT = """\
You know where companies list their open jobs. Reply with only a JSON object \
(no markdown fences):
{"found": true or false, "listing_url": "...", "search_url_template": "... {query} ..." \
or null, "notes": "..."}

listing_url is the official page that lists the company's open jobs (UK or global), on \
its own careers site or jobs platform (Workday, Greenhouse, Lever, Oracle, SuccessFactors, \
etc.), never a job board like LinkedIn or Indeed. Give search_url_template only if you know \
the site's keyword search URL format. If you are not confident the URL exists, return \
found=false — it will be checked."""


class CareersPage(BaseModel):
    """Where a company lists its jobs."""

    model_config = ConfigDict(extra="ignore")

    listing_url: str
    search_url_template: str | None = None
    notes: str | None = None

    def url_for(self, role: str) -> str:
        """The page to fetch for *role* — its search results when a template is known."""
        if self.search_url_template and "{query}" in self.search_url_template:
            return self.search_url_template.replace("{query}", quote_plus(role))
        return self.listing_url

    def is_search(self) -> bool:
        """True when ``url_for`` returns keyword search results (already role-filtered)."""
        return bool(self.search_url_template and "{query}" in self.search_url_template)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    found: bool
    listing_url: str | None = None
    search_url_template: str | None = None
    notes: str | None = None


def _last_json_object(text: str) -> str | None:
    """Return the last ``{...}`` span in *text* (the model's final answer)."""
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    end = clean.rfind("}")
    if end == -1:
        return None
    depth = 0
    for i in range(end, -1, -1):
        if clean[i] == "}":
            depth += 1
        elif clean[i] == "{":
            depth -= 1
            if depth == 0:
                return clean[i : end + 1]
    return None


def _parse_answer(text: str) -> CareersPage | None:
    raw = _last_json_object(text)
    if raw is None:
        return None
    try:
        answer = _Answer.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        return None
    if not answer.found or not answer.listing_url:
        return None
    if not answer.listing_url.startswith(("http://", "https://")):
        return None
    template = answer.search_url_template
    if template and not template.startswith(("http://", "https://")):
        template = None
    return CareersPage(
        listing_url=answer.listing_url, search_url_template=template, notes=answer.notes
    )


class CareersPageFinder:
    """Find (and cache) each company's careers job-listing page."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        cache: CacheClient,
        *,
        http: httpx.AsyncClient | None = None,
        robots: RobotsChecker | None = None,
        meter: CostMeter | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._http = http
        self._robots = robots
        self._meter = meter

    async def is_cached(self, company: str) -> bool:
        """True when a still-valid lookup result is saved (no Claude call needed)."""
        return await self._load(self._key(company)) is not None

    async def find(self, company: str) -> CareersPage | None:
        """Return the careers page for *company*, or ``None`` when none could be found.

        Raises the meter's BudgetStop / EmployerLimit when limits stop the lookup.
        """
        key = self._key(company)
        cached = await self._load(key)
        if cached is not None:
            found, page = cached
            return page if found else None

        try:
            page = _parse_answer(await self._ask(company, search=False))
            if page is not None and not await self._is_jobs_page(page.listing_url):
                page = None
            if page is None:
                page = _parse_answer(await self._ask(company, search=True))
        except (anthropic.APIError, CallFailed):
            return None  # transient failure: don't cache, try again next run
        await self._cache.set_cached(
            key,
            json.dumps(
                {
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "page": page.model_dump() if page else None,
                }
            ),
        )
        return page

    @staticmethod
    def _key(company: str) -> str:
        return cache_key("careers_page_v1", normalise_company(company))

    async def _is_jobs_page(self, url: str) -> bool:
        """Free check that *url* loads and looks like a job listing page."""
        if self._http is None:
            return True  # nothing to check with
        if self._robots is not None and not await self._robots.allowed(url):
            return True  # can't check politely; the site reader will report robots.txt
        try:
            resp = await self._http.get(
                url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
            )
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        if board_from_url(str(resp.url)) or board_from_url(resp.text):
            return True
        lowered = resp.text.lower()
        return sum(word in lowered for word in _JOBS_PAGE_WORDS) >= _MIN_JOBS_WORDS

    async def _ask(self, company: str, *, search: bool) -> str:
        """Ask Claude for the page — from memory, or with web search — and return its text."""
        step = "finding careers page (web search)" if search else "finding careers page"
        kwargs: dict[str, Any] = {
            "model": _MODEL,
            "max_tokens": 2048 if search else 300,
            "system": _SYSTEM_PROMPT if search else _GUESS_PROMPT,
        }
        if search:
            kwargs["tools"] = [_WEB_SEARCH_TOOL]
        messages: list[anthropic.types.MessageParam] = [
            {"role": "user", "content": f"Company: {company}"}
        ]
        response = await metered_create(
            self._client, self._meter, company, step, messages=messages, **kwargs
        )
        for _ in range(_MAX_CONTINUATIONS):
            if response.stop_reason != "pause_turn":
                break
            # Resume the paused server-side search loop: resend with the partial turn.
            messages = [*messages, {"role": "assistant", "content": response.content}]
            response = await metered_create(
                self._client, self._meter, company, step, messages=messages, **kwargs
            )
        return "".join(
            block.text for block in response.content if isinstance(block, anthropic.types.TextBlock)
        )

    async def _load(self, key: str) -> tuple[bool, CareersPage | None] | None:
        raw = await self._cache.get_cached(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            saved_at = datetime.fromisoformat(data["saved_at"])
            page = CareersPage.model_validate(data["page"]) if data["page"] else None
        except (ValueError, KeyError, TypeError, ValidationError):
            return None
        max_age = _FOUND_MAX_AGE if page else _NOT_FOUND_MAX_AGE
        if datetime.now(timezone.utc) - saved_at > max_age:
            return None
        return (page is not None, page)
