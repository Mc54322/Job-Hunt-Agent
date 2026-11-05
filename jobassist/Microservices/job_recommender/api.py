"""FastAPI app for the job_recommender service.

The primary service: scores postings against a résumé, ranks them, and orchestrates
the whole pipeline via `POST /recommend` (the front-end entry point). Also hosts the
shared LLM-response cache + posting store that the other services call over HTTP.
Run standalone: `uvicorn jobassist.Microservices.job_recommender.api:app --port 8003`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import os
import tempfile
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from jobassist.Microservices.job_recommender.cache_client import LocalCacheClient
from jobassist.Microservices.job_recommender.clients import DataCleanerClient, WebScraperClient
from jobassist.Microservices.job_recommender.models import (
    CompanySearchStatus,
    CostLine,
    JobPosting,
    JobQuery,
    ScoredPosting,
)
from jobassist.Microservices.job_recommender.orchestration.employers_file import load_employers
from jobassist.Microservices.job_recommender.orchestration.pipeline import (
    DEFAULT_BUDGET_USD,
    DEFAULT_COMPANY_BUDGET_USD,
    PipelineOptions,
    RunState,
    friendly_error,
    run_pipeline,
)
from jobassist.Microservices.job_recommender.orchestration.resume_file import (
    ResumeReadError,
    read_resume,
)
from jobassist.Microservices.job_recommender.persistence.store import Store
from jobassist.Microservices.job_recommender.reporting.report import _render
from jobassist.Microservices.job_recommender.scoring.scorer import ScoringPipeline


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    default_db = Path.home() / ".jobassist" / "data.db"
    store = Store(os.environ.get("JOBASSIST_DB", str(default_db)))
    async with httpx.AsyncClient(timeout=60.0) as http:
        app.state.store = store
        app.state.http = http
        yield
    store.close()


app = FastAPI(title="JobAssist — Job Recommender", version="0.1.0", lifespan=lifespan)

# Background runs started by the web UI, newest last. Bounded: oldest are dropped.
_RUNS: OrderedDict[str, RunState] = OrderedDict()
_RUN_TASKS: set[asyncio.Task[None]] = set()
_MAX_RUNS = 20


def get_anthropic() -> anthropic.AsyncAnthropic | None:
    """Return an Anthropic client, or None when no API key is configured."""
    try:
        return anthropic.AsyncAnthropic()
    except Exception:  # noqa: BLE001 - missing key → scoring unavailable
        return None


# --- Request / response models ---


class CacheGetRequest(BaseModel):
    key: str


class CacheGetResponse(BaseModel):
    value: str | None


class CacheSetRequest(BaseModel):
    key: str
    value: str


class ScoreRequest(BaseModel):
    posting: JobPosting
    resume: str


class RecommendRequest(BaseModel):
    query: JobQuery
    resume: str
    one_per_company: bool = True
    expand_aliases: bool = True
    refresh: bool = False  # ignore saved search results and search again
    search_company_sites: bool = False  # also search each named company's website
    budget_usd: float | None = DEFAULT_BUDGET_USD  # Claude spend limit for the run
    company_budget_usd: float | None = DEFAULT_COMPANY_BUDGET_USD  # per-employer limit
    deep_search: bool = False  # web-search fallback for careers pages (expensive)


class RecommendResponse(BaseModel):
    results: list[ScoredPosting]
    companies: list[CompanySearchStatus] = []
    spent_usd: float = 0.0
    costs: list[CostLine] = []
    stop_reason: str | None = None


class RunStarted(BaseModel):
    run_id: str


class RunStatus(BaseModel):
    run_id: str
    state: str
    phase: str
    message: str
    done: int
    total: int
    results: list[ScoredPosting]
    companies: list[CompanySearchStatus]
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    budget_usd: float | None
    spent_usd: float
    costs: list[CostLine]
    stop_reason: str | None
    unscored: int
    unscored_postings: list[JobPosting]


class EstimateRequest(BaseModel):
    query: JobQuery
    search_company_sites: bool = False
    expand_aliases: bool = True
    deep_search: bool = False
    budget_usd: float | None = None
    company_budget_usd: float | None = DEFAULT_COMPANY_BUDGET_USD


class EstimateResponse(BaseModel):
    low_usd: float
    high_usd: float
    boards: int
    adzuna: int
    websites: int
    careers_pages_to_find: int


class TitlesRequest(BaseModel):
    role: str


class TitlesResponse(BaseModel):
    titles: list[str]


class SavedRequest(BaseModel):
    resume: str | None = None  # when given, include scores already saved for this CV


class SavedJob(BaseModel):
    posting: JobPosting
    first_seen: str
    score: float | None = None
    rationale: str | None = None


class SavedResponse(BaseModel):
    jobs: list[SavedJob]


class FileUpload(BaseModel):
    filename: str
    content_base64: str


class EmployerRow(BaseModel):
    name: str
    careers_url: str | None
    bucket: str | None
    starred: bool


class EmployersResponse(BaseModel):
    employers: list[EmployerRow]
    buckets: list[str]


class ResumeResponse(BaseModel):
    text: str


class ReportRequest(BaseModel):
    results: list[ScoredPosting]
    query: JobQuery


# --- Health ---


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "job_recommender"}


# --- Shared cache / storage API (called by web_scraper + cv_feedback) ---


@app.post("/cache/get", response_model=CacheGetResponse)
async def cache_get(req: CacheGetRequest, request: Request) -> CacheGetResponse:
    store: Store = request.app.state.store
    return CacheGetResponse(value=store.get_cached(req.key))


@app.post("/cache/set")
async def cache_set(req: CacheSetRequest, request: Request) -> dict[str, bool]:
    store: Store = request.app.state.store
    store.set_cached(req.key, req.value)
    return {"ok": True}


@app.post("/postings")
async def save_posting(posting: JobPosting, request: Request) -> dict[str, bool]:
    store: Store = request.app.state.store
    store.save(posting)
    return {"ok": True}


@app.get("/postings", response_model=dict[str, list[JobPosting]])
async def list_postings(request: Request) -> dict[str, list[JobPosting]]:
    store: Store = request.app.state.store
    return {"postings": store.all_postings()}


# --- Scoring ---


@app.post("/score", response_model=ScoredPosting)
async def score(
    req: ScoreRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> ScoredPosting:
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")
    cache = LocalCacheClient(request.app.state.store)
    pipeline = ScoringPipeline(client, req.resume, cache)
    return await pipeline.score(req.posting)


# --- Report ---


@app.post("/report", response_model=dict[str, str])
async def report(req: ReportRequest) -> dict[str, str]:
    return {"markdown": _render(req.results, req.query)}


# --- Orchestration (front-end entry point) ---


def _services(request: Request) -> tuple[WebScraperClient, DataCleanerClient]:
    http: httpx.AsyncClient = request.app.state.http
    return (
        WebScraperClient(os.environ.get("WEB_SCRAPER_URL", "http://localhost:8001"), http),
        DataCleanerClient(os.environ.get("DATA_CLEANER_URL", "http://localhost:8002"), http),
    )


def _options(req: RecommendRequest) -> PipelineOptions:
    return PipelineOptions(
        query=req.query,
        resume=req.resume,
        one_per_company=req.one_per_company,
        expand_aliases=req.expand_aliases,
        refresh=req.refresh,
        search_company_sites=req.search_company_sites,
        budget_usd=req.budget_usd,
        company_budget_usd=req.company_budget_usd,
        deep_search=req.deep_search,
    )


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> RecommendResponse:
    """Full pipeline: scrape → dedupe → score → rank, over HTTP to the other services."""
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")
    web_scraper, data_cleaner = _services(request)
    state = RunState()
    await run_pipeline(
        _options(req), client, web_scraper, data_cleaner, request.app.state.store, state
    )
    return RecommendResponse(
        results=state.results,
        companies=state.companies,
        spent_usd=state.spent_usd,
        costs=state.costs,
        stop_reason=state.stop_reason,
    )


# --- Background runs (web UI) ---


@app.post("/runs", response_model=RunStarted)
async def start_run(
    req: RecommendRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> RunStarted:
    """Start the pipeline in the background; poll `GET /runs/{id}` for progress."""
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="The Anthropic API key is missing. Add ANTHROPIC_API_KEY to the .env file.",
        )
    web_scraper, data_cleaner = _services(request)
    state = RunState()
    _RUNS[state.id] = state
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.popitem(last=False)

    async def _run() -> None:
        try:
            await run_pipeline(
                _options(req), client, web_scraper, data_cleaner, request.app.state.store, state
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as run state
            state.state = "error"
            state.error = friendly_error(exc)
            state.finished_at = datetime.now(state.started_at.tzinfo)

    task = asyncio.create_task(_run())
    _RUN_TASKS.add(task)
    task.add_done_callback(_RUN_TASKS.discard)
    return RunStarted(run_id=state.id)


@app.get("/runs/{run_id}", response_model=RunStatus)
async def run_status(run_id: str, request: Request) -> RunStatus:
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown run")
    if state.state == "running" and state.phase == "searching":
        web_scraper, _ = _services(request)
        progress = await web_scraper.progress(run_id)
        if progress is not None:
            state.done, state.total = progress.done, progress.total
            state.spent_usd = progress.spent_usd
            if progress.current and not state.stop_requested:
                state.message = f"Searching — last checked: {progress.current}"
    return RunStatus(
        run_id=state.id,
        state=state.state,
        phase=state.phase,
        message=state.message,
        done=state.done,
        total=state.total,
        results=state.results,
        companies=state.companies,
        error=state.error,
        started_at=state.started_at,
        finished_at=state.finished_at,
        budget_usd=state.budget_usd,
        spent_usd=state.spent_usd,
        costs=state.costs,
        stop_reason=state.stop_reason,
        unscored=state.unscored,
        unscored_postings=state.unscored_postings,
    )


@app.post("/runs/{run_id}/stop", response_model=RunStatus)
async def stop_run(run_id: str, request: Request) -> RunStatus:
    """The page's Stop button: stop searching/scoring now and keep what's done."""
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="unknown run")
    if state.state == "running":
        state.stop_requested = True
        if state.scoring_meter is not None:
            # Already scoring: stop scoring and show what's scored.
            state.message = "Stopping scoring…"
            state.scoring_meter.cancel()
        else:
            # Still searching: end the search; the pipeline then scores what was found.
            state.message = "Stopping the search — scoring the jobs found so far…"
            web_scraper, _ = _services(request)
            await web_scraper.stop(run_id)
    return await run_status(run_id, request)


# Mirrors web_scraper's reserve for one web-search call (services don't share code).
WEB_SEARCH_RESERVE_USD = 0.40
# Per-step costs (claude-sonnet-4-6) measured on real runs, for the pre-run estimate.
_FIND_PAGE_USD = (0.0015, 0.003)  # from memory + free checks
_WEB_SEARCH_USD = (0.11, 0.76)  # deep search fallback — measured Nov 2026
_READ_SITE_USD = (0.0, 0.05)  # free when the page doesn't mention the role
_SCORE_USD = (0.004, 0.012)
_TITLES_USD = 0.002


@app.post("/estimate", response_model=EstimateResponse)
async def estimate(req: EstimateRequest, request: Request) -> EstimateResponse:
    """A rough cost range for a search before it runs (saved results cost nothing)."""
    web_scraper, _ = _services(request)
    plan = await web_scraper.plan(req.query, search_company_sites=req.search_company_sites)
    jobs = req.query.max_results
    titles = _TITLES_USD if req.expand_aliases else 0.0
    per_employer_cap = req.company_budget_usd if req.company_budget_usd is not None else 1e9
    # Deep search only runs where the per-employer limit leaves room for its reserve.
    deep_high = (
        min(_WEB_SEARCH_USD[1], per_employer_cap)
        if req.deep_search and per_employer_cap >= WEB_SEARCH_RESERVE_USD
        else 0.0
    )
    low = (
        titles + plan.careers_pages_to_find * _FIND_PAGE_USD[0]
        + plan.websites * _READ_SITE_USD[0] + jobs * _SCORE_USD[0] * 0.5
    )
    high = (
        titles + plan.careers_pages_to_find * (_FIND_PAGE_USD[1] + deep_high)
        + plan.websites * min(_READ_SITE_USD[1], per_employer_cap) + jobs * _SCORE_USD[1]
    )
    if req.budget_usd is not None:
        high = min(high, req.budget_usd)
        low = min(low, high)
    return EstimateResponse(
        low_usd=round(low, 2),
        high_usd=round(high, 2),
        boards=plan.boards,
        adzuna=plan.adzuna,
        websites=plan.websites,
        careers_pages_to_find=plan.careers_pages_to_find,
    )


@app.post("/titles", response_model=TitlesResponse)
async def similar_titles(req: TitlesRequest, request: Request) -> TitlesResponse:
    """Similar job titles to search too. Claude is asked once per title, ever."""
    role = " ".join(req.role.split())
    if not role:
        return TitlesResponse(titles=[])
    web_scraper, _ = _services(request)
    try:
        titles = await web_scraper.similar_titles(role)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="Similar titles need the Anthropic API key in the .env file.",
            ) from exc
        raise
    seen = {role.lower()}
    unique: list[str] = []
    for title in titles:
        if title.lower() not in seen:
            seen.add(title.lower())
            unique.append(title)
    return TitlesResponse(titles=unique)


@app.post("/saved", response_model=SavedResponse)
async def saved_jobs(
    req: SavedRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> SavedResponse:
    """Every job found so far, with scores already saved for *resume* — no searching and
    no Claude calls (scores come only from the cache)."""
    store: Store = request.app.state.store
    pipeline = (
        ScoringPipeline(client, req.resume, LocalCacheClient(store))
        if req.resume and client is not None
        else None
    )
    jobs: list[SavedJob] = []
    for posting, first_seen in store.saved_postings():
        scored = await pipeline.cached_score(posting) if pipeline else None
        jobs.append(
            SavedJob(
                posting=posting,
                first_seen=first_seen,
                score=scored.score if scored else None,
                rationale=scored.rationale if scored else None,
            )
        )
    return SavedResponse(jobs=jobs)


# --- File helpers (web UI) ---


def _decode(upload: FileUpload) -> bytes:
    try:
        return base64.b64decode(upload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="the file upload was corrupted") from exc


@app.post("/employers/parse", response_model=EmployersResponse)
async def parse_employers(upload: FileUpload) -> EmployersResponse:
    """Read an uploaded Excel employer list (all rows; the UI filters stars/buckets)."""
    data = _decode(upload)
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            targets = load_employers(Path(tmp.name))
        except Exception as exc:  # noqa: BLE001 - openpyxl raises many types for bad files
            raise HTTPException(
                status_code=400,
                detail=f"Couldn't read that spreadsheet: {exc}. "
                "It needs a sheet with a 'Company' column.",
            ) from exc
    employers = [
        EmployerRow(name=t.name, careers_url=t.careers_url, bucket=t.bucket, starred=t.starred)
        for t in targets
    ]
    buckets = sorted({t.bucket for t in targets if t.bucket})
    return EmployersResponse(employers=employers, buckets=buckets)


@app.post("/resume/parse", response_model=ResumeResponse)
async def parse_resume(upload: FileUpload) -> ResumeResponse:
    """Turn an uploaded CV (PDF, .docx, .txt) into text."""
    try:
        return ResumeResponse(text=read_resume(upload.filename, _decode(upload)))
    except ResumeReadError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't read that CV: {exc}") from exc


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8003")))
