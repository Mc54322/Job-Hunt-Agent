"""Data models owned by the job_recommender service.

Each service defines its own copy of the wire shapes it speaks (no shared schema
import) so it can run and deploy independently. The shapes are kept structurally
identical across services so JSON round-trips cleanly between them.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel, Field, computed_field


def posting_hash(company: str, role: str, location: str) -> str:
    """Stable dedup key: sha256 of lowercased company|role|location."""
    raw = f"{company.lower()}|{role.lower()}|{location.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


class JobQuery(BaseModel):
    """Parameters that drive a single job search run."""

    role: str = Field(..., description="Job title / role to search for")
    job_type: str = Field(..., description="Employment type, e.g. 'full-time'")
    location: str | None = Field(None, description="Geographic filter, e.g. 'London, UK'")
    companies: list[str] = Field(default_factory=list, description="Specific companies to target")
    max_results: int = Field(50, gt=0, description="Maximum postings to return across all sources")
    company_urls: dict[str, str] = Field(
        default_factory=dict, description="Optional careers-page URL per company"
    )


class JobPosting(BaseModel):
    """A single job posting as produced by any source."""

    company: str
    role: str
    location: str
    url: str
    source: str = Field(..., description="Identifier of the source that produced this posting")
    posted_date: date | None = None
    description: str | None = None
    salary_raw: str | None = Field(None, description="Salary string exactly as found")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hash(self) -> str:
        return posting_hash(self.company, self.role, self.location)


class ScoredPosting(BaseModel):
    """A `JobPosting` with a relevance score and rationale attached."""

    posting: JobPosting
    score: float = Field(..., ge=0.0, le=1.0, description="Fit score between 0 and 1")
    rationale: str = Field(..., description="One-paragraph explanation of the score")


class CompanySearchStatus(BaseModel):
    """What was searched for one company and how many postings each source produced."""

    company: str
    found: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0


class CostLine(BaseModel):
    """Estimated Claude spend for one employer and step."""

    company: str
    step: str
    usd: float
    calls: int
    web_searches: int
