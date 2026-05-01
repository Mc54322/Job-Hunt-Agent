"""Core Pydantic schemas shared across the entire pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
