"""Data models owned by the web_scraper service.

Own copy of the wire shapes (no shared schema import). web_scraper is the leaf
that produces `JobPosting`s from a `JobQuery`; downstream services keep their own
structurally-identical copies.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel, Field, computed_field


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
