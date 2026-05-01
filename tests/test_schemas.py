"""Tests for JobQuery schema validation."""

import pytest
from pydantic import ValidationError

from jobassist.schemas import JobQuery


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
