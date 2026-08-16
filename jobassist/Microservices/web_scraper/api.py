"""FastAPI app for the web_scraper service.

Owns fetching (ATS + aggregators + company pages), role-alias expansion and index
expansion. Reaches the job_recommender `/cache` API for LLM-response caching.
Run standalone: `uvicorn jobassist.Microservices.web_scraper.api:app --port 8001`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from jobassist.Microservices.web_scraper.cache_client import RemoteCacheClient
from jobassist.Microservices.web_scraper.contracts.base import Source
from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery
from jobassist.Microservices.web_scraper.query_expansion.aliases import AliasGenerator
from jobassist.Microservices.web_scraper.query_expansion.index import (
    KNOWN_INDICES,
    companies_for_index,
)
from jobassist.Microservices.web_scraper.sources.aggregators.adzuna.adzuna import AdzunaFetcher
from jobassist.Microservices.web_scraper.sources.aggregators.reed.reed import ReedFetcher
from jobassist.Microservices.web_scraper.sources.ats.greenhouse.greenhouse import GreenhouseFetcher
from jobassist.Microservices.web_scraper.sources.company_pages.extractor import PageExtractor


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        app.state.http = http
        yield


app = FastAPI(title="JobAssist — Web Scraper", version="0.1.0", lifespan=lifespan)


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
    job_type: str


class AliasResponse(BaseModel):
    aliases: list[str]


class SearchRequest(BaseModel):
    query: JobQuery
    expand_aliases: bool = True


class PostingsResponse(BaseModel):
    postings: list[JobPosting]


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


@app.post("/search", response_model=PostingsResponse)
async def search(
    req: SearchRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> PostingsResponse:
    """Fetch postings across all configured sources for the query (+ role aliases)."""
    query = req.query
    http: httpx.AsyncClient = request.app.state.http

    adzuna_id = os.environ.get("ADZUNA_APP_ID")
    adzuna_key = os.environ.get("ADZUNA_APP_KEY")
    reed_key = os.environ.get("REED_API_KEY")

    roles = [query.role]
    if req.expand_aliases and client is not None:
        generator = AliasGenerator(client, _cache(request))
        roles.extend(await generator.generate(query.role, query.job_type))

    sources: list[Source] = []
    if query.companies:
        sources.append(GreenhouseFetcher(http))
    if adzuna_id and adzuna_key:
        sources.append(AdzunaFetcher(http, adzuna_id, adzuna_key))
    if reed_key:
        sources.append(ReedFetcher(http, reed_key))

    postings: list[JobPosting] = []
    for role_variant in roles:
        variant_query = query.model_copy(update={"role": role_variant})
        for source in sources:
            async for posting in await source.search(variant_query):
                postings.append(posting)

    return PostingsResponse(postings=postings)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8001")))
