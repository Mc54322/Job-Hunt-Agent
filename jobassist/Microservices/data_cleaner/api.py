"""FastAPI app for the data_cleaner service.

Stateless transforms over postings: dedupe, salary normalisation, volume estimate.
Run standalone: `uvicorn jobassist.Microservices.data_cleaner.api:app --port 8002`.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from jobassist.Microservices.data_cleaner.deduplication.dedupe import deduplicate
from jobassist.Microservices.data_cleaner.enrichment.volume import estimate_volume
from jobassist.Microservices.data_cleaner.models import JobPosting, SalaryResult, VolumeResult
from jobassist.Microservices.data_cleaner.normalisation.salary import parse_salary

app = FastAPI(title="JobAssist — Data Cleaner", version="0.1.0")


class DedupeRequest(BaseModel):
    postings: list[JobPosting]


class PostingsResponse(BaseModel):
    postings: list[JobPosting]


class SalaryRequest(BaseModel):
    raw: str | None = None


class VolumeRequest(BaseModel):
    posting: JobPosting


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "data_cleaner"}


@app.post("/dedupe", response_model=PostingsResponse)
async def dedupe(req: DedupeRequest) -> PostingsResponse:
    """Deduplicate a batch of postings (ATS-direct beats aggregator on collision)."""

    async def _stream() -> AsyncIterator[JobPosting]:
        for posting in req.postings:
            yield posting

    unique = [p async for p in deduplicate(_stream())]
    return PostingsResponse(postings=unique)


@app.post("/salary", response_model=SalaryResult | None)
async def salary(req: SalaryRequest) -> SalaryResult | None:
    """Normalise a raw salary string into a canonical range, or null if unparseable."""
    parsed = parse_salary(req.raw)
    if parsed is None:
        return None
    return SalaryResult(
        currency=parsed.currency,
        low=parsed.low,
        high=parsed.high,
        is_annual=parsed.is_annual,
        midpoint=parsed.midpoint,
        text=str(parsed),
    )


@app.post("/volume", response_model=VolumeResult)
async def volume(req: VolumeRequest) -> VolumeResult:
    """Return a heuristic applicant-volume estimate for a posting."""
    est = estimate_volume(req.posting)
    return VolumeResult(
        estimate=est.estimate,
        label=est.label,
        days_open=est.days_open,
        seniority=est.seniority,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8002")))
