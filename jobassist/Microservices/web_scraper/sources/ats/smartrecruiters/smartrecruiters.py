"""SmartRecruiters ATS fetcher — uses the public postings API, no LLM."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from typing import Any, AsyncIterator, Mapping

import httpx

from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery

_POSTINGS_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2
_PAGE_LIMIT = 100


def _slugify(company: str) -> str:
    return company.replace(" ", "")


def _role_matches(title: str, query: JobQuery) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in query.role_terms())


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


def _job_url(job: dict[str, Any], slug: str) -> str:
    """Public job-ad URL; the API's ``ref`` field points at the JSON API, not the ad."""
    identifier = (job.get("company") or {}).get("identifier") or slug
    return f"https://jobs.smartrecruiters.com/{identifier}/{job['id']}"


def _to_posting(job: dict[str, Any], company: str, slug: str) -> JobPosting:
    return JobPosting(
        company=company,
        role=job["name"],
        location=_location(job),
        url=_job_url(job, slug),
        source="smartrecruiters",
        posted_date=_parse_date(job.get("releasedDate", "")),
        description=None,
        salary_raw=None,
    )


class SmartRecruitersFetcher:
    """Fetches postings from SmartRecruiters public company endpoints."""

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
                slug = slugs.get(company) or _slugify(company)
                url = _POSTINGS_URL.format(slug=slug)
                seen: set[str] = set()
                # Server-side `q` search per term: large boards (Experian ~400 ads) would
                # otherwise need many pages, and the API returns only 10 ads by default.
                for term in query.role_terms():
                    try:
                        resp = await client.get(
                            url,
                            params={"q": term, "limit": _PAGE_LIMIT},
                            headers={"User-Agent": _USER_AGENT},
                        )
                        resp.raise_for_status()
                    except httpx.HTTPStatusError:
                        await asyncio.sleep(
                            _RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER)
                        )
                        break
                    except httpx.HTTPError:
                        break

                    for job in resp.json().get("content", []):
                        if job["id"] in seen or not _role_matches(job.get("name", ""), query):
                            continue
                        seen.add(job["id"])
                        yield _to_posting(job, company, slug)

                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
