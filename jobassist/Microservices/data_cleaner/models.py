"""Data models owned by the data_cleaner service.

Own copy of the wire shapes (no shared schema import) plus this service's own
response models for salary normalisation and volume estimation.
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
    """A single job posting — the only wire shape this service consumes."""

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


class SalaryResult(BaseModel):
    """Normalised salary range returned by `POST /salary`."""

    currency: str
    low: float
    high: float
    is_annual: bool
    midpoint: float
    text: str


class VolumeResult(BaseModel):
    """Applicant-volume estimate returned by `POST /volume`."""

    estimate: int
    label: str
    days_open: int
    seniority: str
