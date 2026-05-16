"""Workday ATS fetcher — uses the public JSON jobs API, no LLM."""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_API_URL = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
_JOB_URL = "https://{tenant}.{wd}.myworkdayjobs.com{path}"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2
_PAGE_SIZE = 20


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _to_posting(job: dict[str, Any], company: str, tenant: str, wd: str) -> JobPosting:
    path: str = job.get("externalPath", "")
    return JobPosting(
        company=company,
        role=job["title"],
        location=job.get("locationsText") or "Unknown",
        url=_JOB_URL.format(tenant=tenant, wd=wd, path=path),
        source="workday",
        salary_raw=None,
    )


class WorkdayFetcher:
    """Fetches postings from a Workday careers site JSON API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        company: str,
        tenant: str,
        site: str,
        *,
        wd: str = "wd3",
    ) -> None:
        self._client = client
        self._company = company
        self._tenant = tenant
        self._site = site
        self._wd = wd
        self._api_url = _API_URL.format(tenant=tenant, wd=wd, site=site)

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role*."""
        client = self._client
        company = self._company
        tenant = self._tenant
        wd = self._wd
        api_url = self._api_url

        async def _generate() -> AsyncIterator[JobPosting]:
            offset = 0
            yielded = 0

            while yielded < query.max_results:
                limit = min(_PAGE_SIZE, query.max_results - yielded)
                payload: dict[str, Any] = {
                    "limit": limit,
                    "offset": offset,
                    "searchText": query.role,
                }
                try:
                    resp = await client.post(
                        api_url,
                        json=payload,
                        headers={
                            "User-Agent": _USER_AGENT,
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    break

                data = resp.json()
                postings: list[dict[str, Any]] = data.get("jobPostings", [])
                if not postings:
                    break

                for job in postings:
                    if _role_matches(job.get("title", ""), query.role):
                        yield _to_posting(job, company, tenant, wd)
                        yielded += 1
                        if yielded >= query.max_results:
                            return

                total: int = data.get("total", 0)
                offset += len(postings)
                if offset >= total:
                    break

                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
