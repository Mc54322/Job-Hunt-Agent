"""Tests for all core schemas."""

import pytest
from pydantic import ValidationError

from jobassist.schemas import JobPosting, JobQuery, ScoredPosting, posting_hash

# ---------------------------------------------------------------------------
# JobQuery
# ---------------------------------------------------------------------------


def test_minimal_valid_query() -> None:
    q = JobQuery(role="Software Engineer", job_type="full-time")
    assert q.role == "Software Engineer"
    assert q.job_type == "full-time"
    assert q.location is None
    assert q.companies == []
    assert q.max_results == 50


def test_fully_specified_query() -> None:
    q = JobQuery(
        role="Data Analyst",
        job_type="contract",
        location="London, UK",
        companies=["DeepMind", "Palantir"],
        max_results=20,
    )
    assert q.location == "London, UK"
    assert q.companies == ["DeepMind", "Palantir"]
    assert q.max_results == 20


def test_role_is_required() -> None:
    with pytest.raises(ValidationError):
        JobQuery(job_type="full-time")  # type: ignore[call-arg]


def test_job_type_is_required() -> None:
    with pytest.raises(ValidationError):
        JobQuery(role="Engineer")  # type: ignore[call-arg]


def test_max_results_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        JobQuery(role="Engineer", job_type="full-time", max_results=0)


def test_max_results_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        JobQuery(role="Engineer", job_type="full-time", max_results=-5)


def test_companies_defaults_to_empty_list() -> None:
    q = JobQuery(role="PM", job_type="full-time")
    assert isinstance(q.companies, list)
    assert len(q.companies) == 0


def test_no_hardcoded_graduate_defaults() -> None:
    """role and job_type carry no defaults — every search is explicit."""
    q = JobQuery(role="Graduate Engineer", job_type="graduate")
    assert q.role == "Graduate Engineer"
    assert q.job_type == "graduate"


# ---------------------------------------------------------------------------
# posting_hash
# ---------------------------------------------------------------------------

_POSTING_DEFAULTS = dict(
    company="Acme Corp",
    role="Software Engineer",
    location="London, UK",
    url="https://example.com/job/1",
    source="greenhouse",
)


def test_posting_hash_is_deterministic() -> None:
    h1 = posting_hash("Acme Corp", "Software Engineer", "London, UK")
    h2 = posting_hash("Acme Corp", "Software Engineer", "London, UK")
    assert h1 == h2


def test_posting_hash_is_case_insensitive() -> None:
    h1 = posting_hash("Acme Corp", "Software Engineer", "London, UK")
    h2 = posting_hash("ACME CORP", "SOFTWARE ENGINEER", "LONDON, UK")
    assert h1 == h2


def test_posting_hash_differs_on_different_inputs() -> None:
    h1 = posting_hash("Acme Corp", "Software Engineer", "London, UK")
    h2 = posting_hash("Acme Corp", "Data Analyst", "London, UK")
    assert h1 != h2


def test_posting_hash_is_64_hex_chars() -> None:
    h = posting_hash("Acme Corp", "Engineer", "London")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# JobPosting
# ---------------------------------------------------------------------------


def test_job_posting_minimal() -> None:
    p = JobPosting(**_POSTING_DEFAULTS)
    assert p.company == "Acme Corp"
    assert p.posted_date is None
    assert p.description is None
    assert p.salary_raw is None


def test_job_posting_hash_computed() -> None:
    p = JobPosting(**_POSTING_DEFAULTS)
    expected = posting_hash("Acme Corp", "Software Engineer", "London, UK")
    assert p.hash == expected


def test_job_posting_hash_case_insensitive() -> None:
    p1 = JobPosting(**{**_POSTING_DEFAULTS, "company": "acme corp"})
    p2 = JobPosting(**{**_POSTING_DEFAULTS, "company": "ACME CORP"})
    assert p1.hash == p2.hash


def test_job_posting_required_fields() -> None:
    for field in ("company", "role", "location", "url", "source"):
        incomplete = {k: v for k, v in _POSTING_DEFAULTS.items() if k != field}
        with pytest.raises(ValidationError):
            JobPosting(**incomplete)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ScoredPosting
# ---------------------------------------------------------------------------


def _make_posting() -> JobPosting:
    return JobPosting(**_POSTING_DEFAULTS)


def test_scored_posting_valid() -> None:
    sp = ScoredPosting(posting=_make_posting(), score=0.85, rationale="Strong match.")
    assert sp.score == 0.85


def test_scored_posting_score_bounds() -> None:
    with pytest.raises(ValidationError):
        ScoredPosting(posting=_make_posting(), score=1.1, rationale="x")
    with pytest.raises(ValidationError):
        ScoredPosting(posting=_make_posting(), score=-0.1, rationale="x")


def test_scored_posting_score_boundary_values() -> None:
    ScoredPosting(posting=_make_posting(), score=0.0, rationale="No match.")
    ScoredPosting(posting=_make_posting(), score=1.0, rationale="Perfect match.")
