"""LLM extractor for unknown company career pages — Claude with structured JSON output."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from jobassist.schemas import JobPosting
from jobassist.store import Store, cache_key

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """\
You are a job posting extractor. Given text scraped from a company careers page, \
extract every open job posting you can identify.

Return a JSON object (no markdown fences) with this exact schema:
{
  "postings": [
    {
      "role": "job title as written on the page",
      "location": "city / region / 'Remote' / 'Hybrid' — or 'Unknown' if not stated",
      "url": "absolute URL to view or apply for the job (construct from base URL if relative)",
      "salary_raw": "salary string exactly as it appears, or null",
      "description": "one or two sentences describing the role, or null"
    }
  ]
}

If no postings are found return {"postings": []}.
Only include genuine open positions — ignore expired, draft, or duplicate listings."""


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

    def __init__(self, client: anthropic.AsyncAnthropic, store: Store) -> None:
        self._client = client
        self._store = store

    async def extract(self, company: str, page_url: str, text: str) -> list[JobPosting]:
        """Return `JobPosting` objects extracted from *text* (career page main content).

        Results are cached by content hash so the same page is never sent twice.
        """
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        key = cache_key("extract_v1", content_hash)

        cached = self._store.get_cached(key)
        if cached is not None:
            return self._parse(company, page_url, cached)

        user_msg = (
            f"Company: {company}\n"
            f"Page URL: {page_url}\n\n"
            f"Page text:\n{text[:8000]}"
        )

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )

        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return []

        raw = block.text
        self._store.set_cached(key, raw)
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
