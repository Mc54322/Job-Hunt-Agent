"""LLM extractor for unknown company career pages — Claude with structured JSON output."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from jobassist.Microservices.web_scraper.cache_client import CacheClient, cache_key
from jobassist.Microservices.web_scraper.costs.meter import (
    CostMeter,
    estimate_input_cost,
    metered_create,
)
from jobassist.Microservices.web_scraper.models.schemas import JobPosting

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """\
You are a job posting extractor. Given text scraped from a company careers page, \
extract every open job posting you can identify.

Return a JSON object (no markdown fences) with this exact schema:
{
  "postings": [
    {
      "role": "job title as written on the page",
      "location": "city / region / 'Remote' — add the country when the page makes it clear \
(e.g. 'Exeter, United Kingdom'); 'Unknown' if not stated",
      "url": "URL to view or apply for the job, copied from the page's LINKS list",
      "salary_raw": "salary string exactly as it appears, or null",
      "description": "one or two sentences describing the role, or null"
    }
  ]
}

If no postings are found return {"postings": []}.
Only include genuine open positions — ignore expired, draft, or duplicate listings.
Never invent a URL: use one that appears in the page text or LINKS, or the page URL \
itself if the job has no link of its own."""

# Bounds cost per page (~12k tokens). Careers listing pages fit well within this.
_MAX_PAGE_CHARS = 48_000
_MAX_OUTPUT_TOKENS = 4096


class _RawPosting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    location: str = "Unknown"
    url: str
    salary_raw: str | None = None
    description: str | None = None


class _ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    postings: list[_RawPosting]


def _resolve_url(href: str, base_url: str) -> str:
    """Return an absolute URL, resolving *href* against *base_url* if relative."""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base_url, href)


def _strip_fences(text: str) -> str:
    return re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()


class PageExtractor:
    """Extract structured job postings from raw career-page text using Claude."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        cache: CacheClient,
        *,
        meter: CostMeter | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._meter = meter

    async def extract(
        self,
        company: str,
        page_url: str,
        text: str,
        role_terms: list[str] | None = None,
    ) -> list[JobPosting]:
        """Return `JobPosting` objects extracted from *text* (career page main content).

        With *role_terms*, only jobs matching those titles are requested — writing out
        every job on a big page is the expensive part. Results are cached by content
        hash (+ terms) so the same page is never sent twice.
        """
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        terms_key = "|".join(sorted(t.lower() for t in role_terms)) if role_terms else "*"
        key = cache_key("extract_v4", content_hash, terms_key)

        cached = await self._cache.get_cached(key)
        if cached is not None:
            return self._parse(company, page_url, cached)

        wanted = (
            "Only include jobs whose title matches one of these (or is clearly the same "
            f"kind of role): {', '.join(role_terms)}\n"
            if role_terms
            else ""
        )
        user_msg = (
            f"Company: {company}\n"
            f"Page URL: {page_url}\n"
            f"{wanted}\n"
            f"Page text:\n{text[:_MAX_PAGE_CHARS]}"
        )

        response = await metered_create(
            self._client,
            self._meter,
            company,
            "reading website",
            estimate=estimate_input_cost(len(user_msg) + len(_SYSTEM_PROMPT), 1000),
            model=_MODEL,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return []

        raw = block.text
        await self._cache.set_cached(key, raw)
        return self._parse(company, page_url, raw)

    def _parse(self, company: str, page_url: str, text: str) -> list[JobPosting]:
        try:
            data = json.loads(_strip_fences(text))
            result = _ExtractionResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return []

        postings: list[JobPosting] = []
        for raw in result.postings:
            postings.append(
                JobPosting(
                    company=company,
                    role=raw.role,
                    location=raw.location,
                    url=_resolve_url(raw.url, page_url),
                    source="company_page",
                    salary_raw=raw.salary_raw,
                    description=raw.description,
                )
            )
        return postings
