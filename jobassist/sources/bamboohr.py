"""BambooHR ATS fetcher — uses the public careers list endpoint, no LLM."""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_CAREERS_URL = "https://{slug}.bamboohr.com/careers/list"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _slugify(company: str) -> str:
    return company.lower().replace(" ", "")


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _salary_raw(job: dict[str, Any]) -> str | None:
    lo = job.get("minimumSalary")
    hi = job.get("maximumSalary")
    if lo and hi:
        return f"{lo} – {hi}"
    if lo:
        return str(lo)
    if hi:
        return str(hi)
    return None


def _to_posting(job: dict[str, Any], company: str, slug: str) -> JobPosting:
    job_id = job["id"]
    return JobPosting(
        company=company,
        role=job["jobOpeningName"],
        location=job.get("locationLabel") or "Unknown",
        url=f"https://{slug}.bamboohr.com/careers/{job_id}",
        source="bamboohr",
        posted_date=None,
        description=None,
        salary_raw=_salary_raw(job),
    )


class BambooHRFetcher:
    """Fetches postings from BambooHR public careers pages."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role* from *query.companies*."""
        client = self._client

        async def _generate() -> AsyncIterator[JobPosting]:
            for company in query.companies:
                slug = _slugify(company)
                url = _CAREERS_URL.format(slug=slug)
                try:
                    resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    continue
                except httpx.HTTPError:
                    continue

                for job in resp.json().get("result", []):
                    if _role_matches(job.get("jobOpeningName", ""), query.role):
                        yield _to_posting(job, company, slug)

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
