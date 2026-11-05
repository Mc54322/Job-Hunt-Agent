"""Data models owned by the cv_feedback_provider service.

Own copy of the wire shapes (no shared schema import) plus this service's own
drafted-application response model.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel, Field, computed_field


def posting_hash(company: str, role: str, location: str) -> str:
    """Stable dedup key: sha256 of lowercased company|role|location."""
    raw = f"{company.lower()}|{role.lower()}|{location.lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


class JobPosting(BaseModel):
    """A single job posting — the wire shape this service drafts against."""

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


class DraftedApplication(BaseModel):
    """A drafted cover letter plus tailored CV bullets."""

    cover_letter: str
    bullets: list[str]
