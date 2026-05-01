"""Lever ATS fetcher — uses the public v0 postings JSON endpoint, no LLM."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_POSTINGS_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _slugify(company: str) -> str:
    return company.lower().replace(" ", "-")


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _parse_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


def _to_posting(job: dict[str, Any], company: str) -> JobPosting:
    categories: dict[str, Any] = job.get("categories") or {}
    return JobPosting(
        company=company,
        role=job["text"],
        location=categories.get("location") or "Unknown",
        url=job["hostedUrl"],
        source="lever",
        posted_date=_parse_date(job["createdAt"]) if job.get("createdAt") else None,
        description=job.get("descriptionPlain"),
        salary_raw=None,
    )


class LeverFetcher:
    """Fetches postings from Lever public posting endpoints."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role* from *query.companies*."""
        client = self._client

        async def _generate() -> AsyncIterator[JobPosting]:
            for company in query.companies:
                url = _POSTINGS_URL.format(slug=_slugify(company))
                try:
                    resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    continue
                except httpx.HTTPError:
                    continue

                for job in resp.json():
                    if _role_matches(job.get("text", ""), query.role):
                        yield _to_posting(job, company)

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
