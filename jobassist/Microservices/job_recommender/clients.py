"""HTTP clients the job_recommender orchestrator uses to call the other services."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from jobassist.Microservices.job_recommender.models import (
    CompanySearchStatus,
    CostLine,
    JobPosting,
    JobQuery,
)

_SEARCH_TIMEOUT = 1800.0


@dataclass
class SearchResult:
    """Postings from a web_scraper search plus what was searched per company."""

    postings: list[JobPosting]
    companies: list[CompanySearchStatus] = field(default_factory=list)
    spent_usd: float = 0.0
    costs: list[CostLine] = field(default_factory=list)
    stopped: str | None = None


@dataclass
class SearchProgress:
    """Live progress of a web_scraper search."""

    total: int
    done: int
    current: str
    spent_usd: float = 0.0


@dataclass
class SearchPlan:
    """What a search would do, for the cost estimate."""

    boards: int
    adzuna: int
    websites: int
    careers_pages_to_find: int


class WebScraperClient:
    """Client for the web_scraper service `/search` endpoints."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = client

    async def search(
        self,
        query: JobQuery,
        *,
        expand_aliases: bool = True,
        refresh: bool = False,
        search_company_sites: bool = False,
        run_id: str | None = None,
        budget_usd: float | None = None,
        company_budget_usd: float | None = None,
        deep_search: bool = False,
    ) -> SearchResult:
        resp = await self._http.post(
            f"{self._base}/search",
            json={
                "query": query.model_dump(mode="json"),
                "expand_aliases": expand_aliases,
                "refresh": refresh,
                "search_company_sites": search_company_sites,
                "run_id": run_id,
                "budget_usd": budget_usd,
                "company_budget_usd": company_budget_usd,
                "deep_search": deep_search,
            },
            # Employer lists pace Adzuna at ~3s per employer and read company websites.
            timeout=_SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        return SearchResult(
            postings=[JobPosting.model_validate(p) for p in body["postings"]],
            companies=[CompanySearchStatus.model_validate(c) for c in body.get("companies", [])],
            spent_usd=float(body.get("spent_usd", 0.0)),
            costs=[CostLine.model_validate(c) for c in body.get("costs", [])],
            stopped=body.get("stopped"),
        )

    async def progress(self, run_id: str) -> SearchProgress | None:
        """Return live progress for *run_id*, or None when unavailable."""
        try:
            resp = await self._http.get(f"{self._base}/search/progress/{run_id}", timeout=5.0)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        body = resp.json()
        return SearchProgress(
            total=body["total"],
            done=body["done"],
            current=body["current"],
            spent_usd=float(body.get("spent_usd", 0.0)),
        )

    async def similar_titles(self, role: str) -> list[str]:
        """Similar job titles for *role* (looked up once, then saved permanently)."""
        resp = await self._http.post(
            f"{self._base}/aliases", json={"role": role}, timeout=60.0
        )
        resp.raise_for_status()
        titles: list[str] = resp.json()["aliases"]
        return titles

    async def stop(self, run_id: str) -> None:
        """Ask the search for *run_id* to stop (best effort)."""
        try:
            await self._http.post(f"{self._base}/search/stop/{run_id}", timeout=5.0)
        except httpx.HTTPError:
            pass

    async def plan(self, query: JobQuery, *, search_company_sites: bool) -> SearchPlan:
        resp = await self._http.post(
            f"{self._base}/search/plan",
            json={
                "query": query.model_dump(mode="json"),
                "search_company_sites": search_company_sites,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
        return SearchPlan(
            boards=body["boards"],
            adzuna=body["adzuna"],
            websites=body["websites"],
            careers_pages_to_find=body["careers_pages_to_find"],
        )


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
