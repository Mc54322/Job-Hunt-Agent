"""FastAPI app for the job_recommender service.

The primary service: scores postings against a résumé, ranks them, and orchestrates
the whole pipeline via `POST /recommend` (the front-end entry point). Also hosts the
shared LLM-response cache + posting store that the other services call over HTTP.
Run standalone: `uvicorn jobassist.Microservices.job_recommender.api:app --port 8003`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from jobassist.Microservices.job_recommender.cache_client import LocalCacheClient
from jobassist.Microservices.job_recommender.clients import DataCleanerClient, WebScraperClient
from jobassist.Microservices.job_recommender.models import JobPosting, JobQuery, ScoredPosting
from jobassist.Microservices.job_recommender.persistence.store import Store
from jobassist.Microservices.job_recommender.ranking.filters import top_per_company
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


class RecommendResponse(BaseModel):
    results: list[ScoredPosting]


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


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> RecommendResponse:
    """Full pipeline: scrape → dedupe → score → rank, over HTTP to the other services."""
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    http: httpx.AsyncClient = request.app.state.http
    store: Store = request.app.state.store
    web_scraper = WebScraperClient(
        os.environ.get("WEB_SCRAPER_URL", "http://localhost:8001"), http
    )
    data_cleaner = DataCleanerClient(
        os.environ.get("DATA_CLEANER_URL", "http://localhost:8002"), http
    )

    postings = await web_scraper.search(req.query, expand_aliases=req.expand_aliases)
    unique = await data_cleaner.dedupe(postings)

    pipeline = ScoringPipeline(client, req.resume, LocalCacheClient(store))
    scored: list[ScoredPosting] = []
    for posting in unique:
        scored.append(await pipeline.score(posting))
        store.save(posting)

    if req.one_per_company:
        scored = top_per_company(scored)

    return RecommendResponse(results=scored)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8003")))
