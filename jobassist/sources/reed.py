"""Reed UK job board fetcher — uses the Reed Jobs API v1."""

from __future__ import annotations

import asyncio
import base64
import random
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _auth_header(api_key: str) -> str:
    """Reed API uses HTTP Basic Auth with the API key as username, empty password."""
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return f"Basic {token}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _format_salary(min_val: float | None, max_val: float | None) -> str | None:
    if min_val is None and max_val is None:
        return None
    if min_val is not None and max_val is not None:
        return f"£{int(min_val):,} - £{int(max_val):,}"
    if min_val is not None:
        return f"£{int(min_val):,}+"
    return f"up to £{int(max_val):,}"  # type: ignore[arg-type]


def _to_posting(job: dict[str, Any]) -> JobPosting:
    return JobPosting(
        company=job.get("employerName") or "Unknown",
        role=job["jobTitle"],
        location=job.get("locationName") or "Unknown",
        url=job["jobUrl"],
        source="reed",
        posted_date=_parse_date(job.get("date")),
        description=job.get("jobDescription"),
        salary_raw=_format_salary(job.get("minimumSalary"), job.get("maximumSalary")),
    )


class ReedFetcher:
    """Fetches postings from the Reed UK jobs API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        *,
        results_per_page: int = 100,
    ) -> None:
        self._client = client
        self._auth = _auth_header(api_key)
        self._results_per_page = results_per_page

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query* from Reed."""
        client = self._client
        auth = self._auth
        results_per_page = self._results_per_page

        async def _generate() -> AsyncIterator[JobPosting]:
            yielded = 0
            skip = 0

            while yielded < query.max_results:
                take = min(results_per_page, query.max_results - yielded)
                params: dict[str, str | int] = {
                    "keywords": query.role,
                    "resultsToTake": take,
                    "resultsToSkip": skip,
                }
                if query.location:
                    params["locationName"] = query.location

                try:
                    resp = await client.get(
                        _SEARCH_URL,
                        params=params,
                        headers={
                            "User-Agent": _USER_AGENT,
                            "Authorization": auth,
                        },
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    break

                results: list[dict[str, Any]] = resp.json().get("results", [])
                if not results:
                    break

                for job in results:
                    yield _to_posting(job)
                    yielded += 1
                    if yielded >= query.max_results:
                        return

                total: int = resp.json().get("totalResults", 0)
                skip += len(results)
                if skip >= total or len(results) < take:
                    break

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
