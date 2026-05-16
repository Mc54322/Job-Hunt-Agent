"""SmartRecruiters ATS fetcher — uses the public postings API, no LLM."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_POSTINGS_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _slugify(company: str) -> str:
    return company.replace(" ", "")


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _location(job: dict[str, Any]) -> str:
    loc = job.get("location") or {}
    city = loc.get("city")
    country = loc.get("country")
    if city and country:
        return f"{city}, {country}"
    return city or country or "Unknown"


def _to_posting(job: dict[str, Any], company: str) -> JobPosting:
    company_name = (job.get("company") or {}).get("name") or company
    return JobPosting(
        company=company_name,
        role=job["name"],
        location=_location(job),
        url=job["ref"],
        source="smartrecruiters",
        posted_date=_parse_date(job.get("releasedDate", "")),
        description=None,
        salary_raw=None,
    )


class SmartRecruitersFetcher:
    """Fetches postings from SmartRecruiters public company endpoints."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role* from *query.companies*."""
        client = self._client

        async def _generate() -> AsyncIterator[JobPosting]:
            for company in query.companies:
                url = _POSTINGS_URL.format(slug=_slugify(company))
                try:
                    resp = await client.get(
                        url,
                        params={"q": query.role},
                        headers={"User-Agent": _USER_AGENT},
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    continue
                except httpx.HTTPError:
                    continue

                for job in resp.json().get("content", []):
                    if _role_matches(job.get("name", ""), query.role):
                        yield _to_posting(job, company)

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
