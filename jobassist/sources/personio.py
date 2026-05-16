"""Personio ATS fetcher — uses the public positions API, no LLM."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_POSITIONS_URL = "https://{slug}.jobs.personio.com/api/v1/positions"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _slugify(company: str) -> str:
    return company.lower().replace(" ", "-")


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _to_posting(job: dict[str, Any], company: str) -> JobPosting:
    return JobPosting(
        company=company,
        role=job["name"],
        location=job.get("office") or "Unknown",
        url=job["url"],
        source="personio",
        posted_date=_parse_date(job.get("created_at", "")),
        description=None,
        salary_raw=None,
    )


class PersonioFetcher:
    """Fetches postings from Personio public job pages."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role* from *query.companies*."""
        client = self._client

        async def _generate() -> AsyncIterator[JobPosting]:
            for company in query.companies:
                url = _POSITIONS_URL.format(slug=_slugify(company))
                try:
                    resp = await client.get(
                        url,
                        params={"language": "en"},
                        headers={"User-Agent": _USER_AGENT},
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    continue
                except httpx.HTTPError:
                    continue

                jobs: list[Any] = resp.json() if isinstance(resp.json(), list) else []
                for job in jobs:
                    if _role_matches(job.get("name", ""), query.role):
                        yield _to_posting(job, company)

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
