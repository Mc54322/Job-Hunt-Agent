"""FastAPI app for the web_scraper service.

Owns fetching (ATS + aggregators + company pages), role-alias expansion and index
expansion. Reaches the job_recommender `/cache` API for LLM-response caching.
Run standalone: `uvicorn jobassist.Microservices.web_scraper.api:app --port 8001`.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from jobassist.Microservices.web_scraper.cache_client import RemoteCacheClient
from jobassist.Microservices.web_scraper.costs.meter import (
    BudgetStop,
    CallFailed,
    CostLine,
    CostMeter,
)
from jobassist.Microservices.web_scraper.employers.registry import plan_employers
from jobassist.Microservices.web_scraper.models.schemas import (
    CompanySearchStatus,
    JobPosting,
    JobQuery,
)
from jobassist.Microservices.web_scraper.orchestration.employer_search import (
    EMPLOYER_SEARCH_DELAY,
    EmployerSearch,
    SearchProgress,
    SearchSettings,
)
from jobassist.Microservices.web_scraper.query_expansion.aliases import AliasGenerator
from jobassist.Microservices.web_scraper.query_expansion.index import (
    KNOWN_INDICES,
    companies_for_index,
)
from jobassist.Microservices.web_scraper.sources.company_pages.discovery import CareersPageFinder
from jobassist.Microservices.web_scraper.sources.company_pages.extractor import PageExtractor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        app.state.http = http
        yield


app = FastAPI(title="JobAssist — Web Scraper", version="0.1.0", lifespan=lifespan)

_EMPLOYER_SEARCH_DELAY = EMPLOYER_SEARCH_DELAY
# Live progress per run id, for the UI. Bounded: oldest runs are dropped.
_PROGRESS: OrderedDict[str, SearchProgress] = OrderedDict()
_MAX_TRACKED_RUNS = 50


def get_anthropic() -> anthropic.AsyncAnthropic | None:
    """Return an Anthropic client, or None when no API key is configured."""
    try:
        return anthropic.AsyncAnthropic()
    except Exception:  # noqa: BLE001 - missing key / config → feature simply unavailable
        return None


def _cache(request: Request) -> RemoteCacheClient:
    base = os.environ.get("JOB_RECOMMENDER_URL", "http://localhost:8003")
    return RemoteCacheClient(base, request.app.state.http)


class AliasRequest(BaseModel):
    role: str
    job_type: str | None = None


class AliasResponse(BaseModel):
    aliases: list[str]


class SearchRequest(BaseModel):
    query: JobQuery
    expand_aliases: bool = True
    refresh: bool = False  # ignore saved results and search again
    search_company_sites: bool = False  # also search each named company's own website
    run_id: str | None = None  # progress is published under this id when given
    budget_usd: float | None = None  # stop making Claude calls past this spend
    company_budget_usd: float | None = None  # per-employer Claude spend limit
    deep_search: bool = False  # web-search fallback for careers pages (expensive)


class PostingsResponse(BaseModel):
    postings: list[JobPosting]
    companies: list[CompanySearchStatus] = []
    spent_usd: float = 0.0
    costs: list[CostLine] = []
    stopped: str | None = None  # why Claude calls stopped early, if they did


class ProgressResponse(BaseModel):
    total: int
    done: int
    current: str
    spent_usd: float


class PlanRequest(BaseModel):
    query: JobQuery
    search_company_sites: bool = False


class PlanResponse(BaseModel):
    """What a search would do — for the page's cost estimate. No Claude calls."""

    boards: int
    adzuna: int
    websites: int
    careers_pages_to_find: int


class ExtractRequest(BaseModel):
    company: str
    page_url: str
    text: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "web_scraper"}


@app.get("/indices", response_model=dict[str, list[str]])
async def indices() -> dict[str, list[str]]:
    return {"indices": sorted(KNOWN_INDICES)}


@app.get("/companies/{index}", response_model=dict[str, list[str]])
async def companies(index: str) -> dict[str, list[str]]:
    try:
        return {"companies": companies_for_index(index)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/aliases", response_model=AliasResponse)
async def aliases(
    req: AliasRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> AliasResponse:
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")
    generator = AliasGenerator(client, _cache(request))
    return AliasResponse(aliases=await generator.generate(req.role, req.job_type))


@app.post("/extract", response_model=PostingsResponse)
async def extract(
    req: ExtractRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> PostingsResponse:
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")
    extractor = PageExtractor(client, _cache(request))
    postings = await extractor.extract(req.company, req.page_url, req.text)
    return PostingsResponse(postings=postings)


@app.get("/search/progress/{run_id}", response_model=ProgressResponse)
async def search_progress(run_id: str) -> ProgressResponse:
    progress = _PROGRESS.get(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return ProgressResponse(
        total=progress.total,
        done=progress.done,
        current=progress.current,
        spent_usd=round(progress.meter.spent_usd, 4) if progress.meter else 0.0,
    )


@app.post("/search/stop/{run_id}")
async def stop_search(run_id: str) -> dict[str, bool]:
    """The user's Stop button: no more fetching or Claude calls for this run."""
    progress = _PROGRESS.get(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="unknown run")
    progress.stop()
    return {"ok": True}


@app.post("/search/plan", response_model=PlanResponse)
async def search_plan(
    req: PlanRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> PlanResponse:
    query = req.query
    boards, unresolved = plan_employers(query.companies, query.company_urls)
    adzuna = bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))
    websites = len(unresolved) if req.search_company_sites else 0
    to_find = 0
    if websites and client is not None:
        finder = CareersPageFinder(client, _cache(request))
        for company in unresolved:
            if company not in query.company_urls and not await finder.is_cached(company):
                to_find += 1
    return PlanResponse(
        boards=sum(len(s) for s in boards.values()),
        adzuna=len(unresolved) if adzuna else 0,
        websites=websites,
        careers_pages_to_find=to_find,
    )


@app.post("/search", response_model=PostingsResponse)
async def search(
    req: SearchRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> PostingsResponse:
    """Fetch postings for the query (+ role aliases).

    With named companies: each company's known ATS board, else an Adzuna search
    filtered to that employer, plus (optionally) the company's own careers website.
    Without: a broad Adzuna + Reed search. Results are reused for 24h unless `refresh`.
    """
    query = req.query
    adzuna_id = os.environ.get("ADZUNA_APP_ID")
    adzuna_key = os.environ.get("ADZUNA_APP_KEY")
    settings = SearchSettings(
        adzuna=(adzuna_id, adzuna_key) if adzuna_id and adzuna_key else None,
        reed_key=os.environ.get("REED_API_KEY"),
        llm=client,
        refresh=req.refresh,
        company_sites=req.search_company_sites,
        employer_delay=_EMPLOYER_SEARCH_DELAY,
        deep_search=req.deep_search,
    )
    meter = CostMeter(req.budget_usd, req.company_budget_usd)
    settings.meter = meter
    progress = SearchProgress(meter=meter)
    if req.run_id:
        _PROGRESS[req.run_id] = progress
        while len(_PROGRESS) > _MAX_TRACKED_RUNS:
            _PROGRESS.popitem(last=False)

    roles = [query.role]
    if query.role_aliases:
        # Titles chosen on the page: use exactly those, no lookup.
        roles.extend(t for t in query.role_aliases if t.strip())
    elif req.expand_aliases and client is not None:
        generator = AliasGenerator(client, _cache(request), meter=meter)
        try:
            roles.extend(await generator.generate(query.role, query.job_type))
        except (BudgetStop, CallFailed):
            pass  # search on the title alone

    def response(
        postings: list[JobPosting], companies: list[CompanySearchStatus] | None = None
    ) -> PostingsResponse:
        return PostingsResponse(
            postings=postings,
            companies=companies or [],
            spent_usd=round(meter.spent_usd, 4),
            costs=meter.lines(),
            stopped=meter.stopped,
        )

    runner = EmployerSearch(request.app.state.http, _cache(request), settings, progress)
    if query.companies:
        postings, statuses = await runner.search_companies(query, roles)
        return response(postings, statuses)
    return response(await runner.search_broad(query, roles))


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8001")))
