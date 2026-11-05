"""FastAPI app for the cv_feedback_provider service.

Drafts cover letters and tailored CV bullets from résumé + posting facts only.
Reaches the job_recommender `/cache` API for LLM-response caching.
Run standalone: `uvicorn jobassist.Microservices.cv_feedback_provider.api:app --port 8004`.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from jobassist.Microservices.cv_feedback_provider.cache_client import RemoteCacheClient
from jobassist.Microservices.cv_feedback_provider.drafting.drafter import CoverLetterDrafter
from jobassist.Microservices.cv_feedback_provider.models import DraftedApplication, JobPosting


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        app.state.http = http
        yield


app = FastAPI(title="JobAssist — CV Feedback Provider", version="0.1.0", lifespan=lifespan)


def get_anthropic() -> anthropic.AsyncAnthropic | None:
    """Return an Anthropic client, or None when no API key is configured."""
    try:
        return anthropic.AsyncAnthropic()
    except Exception:  # noqa: BLE001 - missing key → feature unavailable
        return None


def _cache(request: Request) -> RemoteCacheClient:
    base = os.environ.get("JOB_RECOMMENDER_URL", "http://localhost:8003")
    return RemoteCacheClient(base, request.app.state.http)


class DraftRequest(BaseModel):
    posting: JobPosting
    resume: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "cv_feedback_provider"}


@app.post("/draft", response_model=DraftedApplication)
async def draft(
    req: DraftRequest,
    request: Request,
    client: anthropic.AsyncAnthropic | None = Depends(get_anthropic),
) -> DraftedApplication:
    if client is None:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")
    drafter = CoverLetterDrafter(client, req.resume, _cache(request))
    return await drafter.draft(req.posting)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8004")))
