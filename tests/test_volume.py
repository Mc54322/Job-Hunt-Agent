"""Tests for the applicant-volume estimate heuristic."""

from __future__ import annotations

from datetime import date, timedelta

from jobassist.schemas import JobPosting
from jobassist.volume import VolumeEstimate, estimate_volume


def _posting(
    role: str = "Software Engineer",
    source: str = "greenhouse",
    posted_date: date | None = None,
) -> JobPosting:
    return JobPosting(
        company="Acme",
        role=role,
        location="London, UK",
        url="https://example.com/job",
        source=source,
        posted_date=posted_date,
    )


# ---------------------------------------------------------------------------
# Return type and label
# ---------------------------------------------------------------------------


def test_returns_volume_estimate() -> None:
    result = estimate_volume(_posting())
    assert isinstance(result, VolumeEstimate)


def test_label_is_valid() -> None:
    result = estimate_volume(_posting())
    assert result.label in {"low", "medium", "high"}


def test_estimate_is_positive() -> None:
    result = estimate_volume(_posting())
    assert result.estimate > 0


# ---------------------------------------------------------------------------
# Seniority detection
# ---------------------------------------------------------------------------


def test_senior_title_gives_senior_seniority() -> None:
    result = estimate_volume(_posting(role="Senior Software Engineer"))
    assert result.seniority == "senior"


def test_junior_title_gives_junior_seniority() -> None:
    result = estimate_volume(_posting(role="Junior Developer"))
    assert result.seniority == "junior"


def test_mid_level_title_gives_mid_seniority() -> None:
    result = estimate_volume(_posting(role="Software Engineer"))
    assert result.seniority == "mid"


def test_graduate_title_gives_junior_seniority() -> None:
    result = estimate_volume(_posting(role="Graduate Software Engineer"))
    assert result.seniority == "junior"


def test_lead_title_gives_senior_seniority() -> None:
    result = estimate_volume(_posting(role="Lead Engineer"))
    assert result.seniority == "senior"


# ---------------------------------------------------------------------------
# Source multiplier (ATS vs aggregator)
# ---------------------------------------------------------------------------


def test_ats_source_lower_estimate_than_aggregator() -> None:
    ats = estimate_volume(_posting(source="greenhouse"))
    agg = estimate_volume(_posting(source="adzuna"))
    assert ats.estimate < agg.estimate


def test_all_ats_sources_accepted() -> None:
    for source in ["greenhouse", "lever", "workday", "ashby",
                   "smartrecruiters", "personio", "teamtailor", "bamboohr"]:
        result = estimate_volume(_posting(source=source))
        assert result.estimate > 0


# ---------------------------------------------------------------------------
# Age factor
# ---------------------------------------------------------------------------


def test_older_posting_has_higher_estimate() -> None:
    fresh = estimate_volume(_posting(posted_date=date.today()))
    old = estimate_volume(_posting(posted_date=date.today() - timedelta(days=60)))
    assert old.estimate > fresh.estimate


def test_no_posted_date_gives_reasonable_estimate() -> None:
    result = estimate_volume(_posting(posted_date=None))
    assert result.estimate > 0
    assert result.days_open == 14  # default assumption


def test_days_open_reflects_posted_date() -> None:
    posted = date.today() - timedelta(days=10)
    result = estimate_volume(_posting(posted_date=posted))
    assert result.days_open == 10


# ---------------------------------------------------------------------------
# Seniority × source interactions
# ---------------------------------------------------------------------------


def test_senior_ats_lowest_competition() -> None:
    senior_ats = estimate_volume(_posting(role="Senior Engineer", source="greenhouse"))
    junior_agg = estimate_volume(_posting(role="Graduate Engineer", source="adzuna"))
    assert senior_ats.estimate < junior_agg.estimate


def test_junior_aggregator_high_label() -> None:
    result = estimate_volume(_posting(
        role="Graduate Software Engineer",
        source="adzuna",
        posted_date=date.today() - timedelta(days=60),
    ))
    assert result.label == "high"
