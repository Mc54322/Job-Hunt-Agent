"""Core Pydantic schemas shared across the entire pipeline."""

from __future__ import annotations

import hashlib
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class JobType(str, Enum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    GRADUATE = "graduate"


class JobQuery(BaseModel):
    """Parameters that drive a single job search run."""

    role: str = Field(..., description="Job title / role to search for, e.g. 'Software Engineer'")
    job_type: str = Field(
        ...,
        description="Employment type, e.g. 'full-time', 'part-time', 'contract', 'internship'",
    )
    location: str | None = Field(None, description="Geographic filter, e.g. 'London, UK'")
    companies: list[str] = Field(
        default_factory=list,
        description="Specific companies to target; empty means search all sources broadly",
    )
    max_results: int = Field(50, gt=0, description="Maximum postings to return across all sources")


def posting_hash(company: str, role: str, location: str) -> str:
    """Stable dedup key: sha256 of lowercased company|role|location."""
    raw = f"{company.lower()}|{role.lower()}|{location.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


class JobPosting(BaseModel):
    """A single job posting as produced by any source."""

    company: str
    role: str
    location: str
    url: str
    source: str = Field(..., description="Identifier of the source that produced this posting")
    posted_date: date | None = None
    description: str | None = None
    salary_raw: str | None = Field(
        None, description="Salary string exactly as found in the posting"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hash(self) -> str:
        return posting_hash(self.company, self.role, self.location)


class ScoredPosting(BaseModel):
    """A `JobPosting` with a relevance score and rationale attached."""

    posting: JobPosting
    score: float = Field(..., ge=0.0, le=1.0, description="Fit score between 0 and 1")
    rationale: str = Field(..., description="One-paragraph explanation of the score")
