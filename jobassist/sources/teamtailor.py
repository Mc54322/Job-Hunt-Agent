"""Teamtailor ATS fetcher — uses the v1 JSON:API, requires an API token."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.schemas import JobPosting, JobQuery

_JOBS_URL = "https://api.teamtailor.com/v1/jobs"
_API_VERSION = "20161108"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2


def _role_matches(title: str, role: str) -> bool:
    return role.lower() in title.lower()


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _build_location_map(included: list[dict[str, Any]]) -> dict[str, str]:
    """Build id → city mapping from JSON:API included resources."""
    result: dict[str, str] = {}
    for item in included:
        if item.get("type") == "locations":
            city = (item.get("attributes") or {}).get("city")
            if city:
                result[item["id"]] = city
    return result


def _location(job: dict[str, Any], loc_map: dict[str, str]) -> str:
    loc_data: list[dict[str, Any]] = (
        (job.get("relationships") or {})
        .get("locations", {})
        .get("data", [])
    )
    if loc_data:
        city = loc_map.get(loc_data[0]["id"])
        if city:
            return city
    return "Unknown"


def _to_posting(job: dict[str, Any], company: str, loc_map: dict[str, str]) -> JobPosting:
    attrs = job.get("attributes") or {}
    links = job.get("links") or {}
    return JobPosting(
        company=company,
        role=attrs["title"],
        location=_location(job, loc_map),
        url=links.get("careersite-job-url") or "",
        source="teamtailor",
        posted_date=_parse_date(attrs.get("created-at", "")),
        description=attrs.get("body-plain"),
        salary_raw=None,
    )


class TeamtailorFetcher:
    """Fetches postings from Teamtailor v1 JSON:API."""

    def __init__(self, client: httpx.AsyncClient, api_key: str, company: str) -> None:
        self._client = client
        self._api_key = api_key
        self._company = company

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query.role*."""
        client = self._client
        headers = {
            "Authorization": f"Token token={self._api_key}",
            "X-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
        }
        company = self._company

        async def _generate() -> AsyncIterator[JobPosting]:
            page = 1
            while True:
                try:
                    resp = await client.get(
                        _JOBS_URL,
                        params={"page[number]": page, "page[size]": 30, "include": "locations"},
                        headers=headers,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))
                    break
                except httpx.HTTPError:
                    break

                data = resp.json()
                jobs: list[dict[str, Any]] = data.get("data", [])
                included: list[dict[str, Any]] = data.get("included", [])
                loc_map = _build_location_map(included)

                for job in jobs:
                    title = (job.get("attributes") or {}).get("title", "")
                    if _role_matches(title, query.role):
                        yield _to_posting(job, company, loc_map)

                total: int = (data.get("meta") or {}).get("total-count", 0)
                if page * 30 >= total:
                    break
                page += 1
                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
