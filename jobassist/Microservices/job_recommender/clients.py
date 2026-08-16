"""HTTP clients the job_recommender orchestrator uses to call the other services."""

from __future__ import annotations

import httpx

from jobassist.Microservices.job_recommender.models import JobPosting, JobQuery


class WebScraperClient:
    """Client for the web_scraper service `/search` endpoint."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = client

    async def search(self, query: JobQuery, *, expand_aliases: bool = True) -> list[JobPosting]:
        resp = await self._http.post(
            f"{self._base}/search",
            json={"query": query.model_dump(mode="json"), "expand_aliases": expand_aliases},
        )
        resp.raise_for_status()
        return [JobPosting.model_validate(p) for p in resp.json()["postings"]]


class DataCleanerClient:
    """Client for the data_cleaner service `/dedupe` endpoint."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = client

    async def dedupe(self, postings: list[JobPosting]) -> list[JobPosting]:
        resp = await self._http.post(
            f"{self._base}/dedupe",
            json={"postings": [p.model_dump(mode="json") for p in postings]},
        )
        resp.raise_for_status()
        return [JobPosting.model_validate(p) for p in resp.json()["postings"]]
