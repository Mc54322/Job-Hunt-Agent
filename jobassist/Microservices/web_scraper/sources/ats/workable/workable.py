"""Workable ATS fetcher — uses the public careers-widget JSON endpoint, no LLM."""

from __future__ import annotations

import asyncio
import random
from datetime import date
from typing import Any, AsyncIterator, Mapping

import httpx

from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery

_WIDGET_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _slugify(company: str) -> str:
    return company.lower().replace(" ", "-")


def _role_matches(title: str, query: JobQuery) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in query.role_terms())


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _location(job: dict[str, Any]) -> str:
    parts = [job.get("city"), job.get("country")]
    location = ", ".join(p for p in parts if p)
    if job.get("telecommuting"):
        return f"{location} (Remote)" if location else "Remote"
    return location or "Unknown"


def _to_posting(job: dict[str, Any], company: str) -> JobPosting:
    return JobPosting(
        company=company,
        role=job["title"],
        location=_location(job),
        url=job["url"],
        source="workable",
        posted_date=_parse_date(job.get("published_on") or ""),
        description=None,
        salary_raw=None,
    )


class WorkableFetcher:
    """Fetches postings from Workable public careers-widget endpoints."""

    def __init__(
        self, client: httpx.AsyncClient, *, slugs: Mapping[str, str] | None = None
    ) -> None:
        self._client = client
        self._slugs = dict(slugs or {})

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role* from *query.companies*."""
        client = self._client
        slugs = self._slugs

        async def _generate() -> AsyncIterator[JobPosting]:
            for company in query.companies:
                url = _WIDGET_URL.format(slug=slugs.get(company) or _slugify(company))
                try:
                    resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    continue
                except httpx.HTTPError:
                    continue

                for job in resp.json().get("jobs", []):
                    if _role_matches(job.get("title", ""), query):
                        yield _to_posting(job, company)

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
