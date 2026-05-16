"""Adzuna aggregator fetcher — UK job search API, free tier."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
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
    company: str = (job.get("company") or {}).get("display_name") or "Unknown"
    location: str = (job.get("location") or {}).get("display_name") or "Unknown"
    return JobPosting(
        company=company,
        role=job["title"],
        location=location,
        url=job["redirect_url"],
        source="adzuna",
        posted_date=_parse_date(job.get("created", "")),
        description=job.get("description"),
        salary_raw=_format_salary(job.get("salary_min"), job.get("salary_max")),
    )


class AdzunaFetcher:
    """Fetches postings from the Adzuna UK jobs API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        app_key: str,
        *,
        results_per_page: int = 50,
    ) -> None:
        self._client = client
        self._app_id = app_id
        self._app_key = app_key
        self._results_per_page = results_per_page

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query* from Adzuna."""
        client = self._client
        app_id = self._app_id
        app_key = self._app_key
        results_per_page = self._results_per_page

        async def _generate() -> AsyncIterator[JobPosting]:
            yielded = 0
            page = 1

            while yielded < query.max_results:
                batch_size = min(results_per_page, query.max_results - yielded)
                params: dict[str, str | int] = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query.role,
                    "results_per_page": batch_size,
                }
                if query.location:
                    params["where"] = query.location

                try:
                    resp = await client.get(
                        _SEARCH_URL.format(page=page),
                        params=params,
                        headers={"User-Agent": _USER_AGENT},
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

                if len(results) < batch_size:
                    break

                page += 1
                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
