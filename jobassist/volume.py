"""Applicant-volume estimate heuristic.

Estimates how competitive a posting likely is based on:
- Seniority level inferred from the job title
- Source type (ATS-direct postings attract fewer spray-and-pray applicants than aggregators)
- Days since the posting was published (older postings have had more time to accumulate)

The output is an ordinal label plus a rough numeric estimate, useful for ranking
postings by expected competition rather than for any absolute count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from jobassist.schemas import JobPosting

# Seniority tiers ordered from least to most competitive
_SENIOR_RE = re.compile(
    r"\b(head|director|vp|vice president|principal|staff|lead|senior|sr\.?)\b", re.I
)
_JUNIOR_RE = re.compile(
    r"\b(junior|jr\.?|graduate|grad|entry.level|intern|apprentice|trainee)\b", re.I
)

# ATS sources draw more targeted applications than broad aggregators
_ATS_SOURCES = frozenset({
    "greenhouse", "lever", "workday", "ashby",
    "smartrecruiters", "personio", "teamtailor", "bamboohr",
})

# Baseline estimates per seniority bucket (annual median applicants)
_SENIOR_BASE = 120
_MID_BASE = 350
_JUNIOR_BASE = 700

# Multipliers
_ATS_MULTIPLIER = 0.6       # direct ATS boards attract fewer bulk applicants
_AGGREGATOR_MULTIPLIER = 1.4  # aggregators amplify reach

# Days-open growth: roughly logarithmic — most applications arrive in the first two weeks
_DAYS_CAP = 60  # after which the rate of new applications slows dramatically


def _seniority_base(title: str) -> int:
    if _SENIOR_RE.search(title):
        return _SENIOR_BASE
    if _JUNIOR_RE.search(title):
        return _JUNIOR_BASE
    return _MID_BASE


def _days_open(posting: JobPosting) -> int:
    if posting.posted_date is None:
        return 14  # assume two weeks when unknown
    delta = (date.today() - posting.posted_date).days
    return max(0, delta)


def _source_multiplier(source: str) -> float:
    if source in _ATS_SOURCES:
        return _ATS_MULTIPLIER
    return _AGGREGATOR_MULTIPLIER


def _age_factor(days: int) -> float:
    """Scale from 0.5 (just posted) to 1.0 (≥ cap days old)."""
    capped = min(days, _DAYS_CAP)
    return 0.5 + 0.5 * (capped / _DAYS_CAP)


@dataclass
class VolumeEstimate:
    estimate: int
    label: str  # "low" | "medium" | "high"
    days_open: int
    seniority: str  # "senior" | "mid" | "junior"


def _label(estimate: int) -> str:
    if estimate < 200:
        return "low"
    if estimate < 500:
        return "medium"
    return "high"


def _seniority_name(title: str) -> str:
    if _SENIOR_RE.search(title):
        return "senior"
    if _JUNIOR_RE.search(title):
        return "junior"
    return "mid"


def estimate_volume(posting: JobPosting) -> VolumeEstimate:
    """Return a heuristic applicant-volume estimate for *posting*."""
    base = _seniority_base(posting.role)
    days = _days_open(posting)
    raw = base * _source_multiplier(posting.source) * _age_factor(days)
    est = round(raw)
    return VolumeEstimate(
        estimate=est,
        label=_label(est),
        days_open=days,
        seniority=_seniority_name(posting.role),
    )
