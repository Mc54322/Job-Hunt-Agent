"""Tests for post-scoring result filters."""

from __future__ import annotations

from jobassist.Microservices.job_recommender.ranking.filters import top_per_company
from jobassist.Microservices.web_scraper.models.schemas import JobPosting, ScoredPosting


def _posting(
    company: str = "Acme",
    role: str = "Engineer",
    location: str = "London",
    url: str = "https://example.com/1",
) -> JobPosting:
    return JobPosting(
        company=company,
        role=role,
        location=location,
        url=url,
        source="greenhouse",
        salary_raw=None,
    )


def _scored(
    company: str = "Acme",
    role: str = "Engineer",
    score: float = 0.5,
    url: str = "https://example.com/1",
) -> ScoredPosting:
    return ScoredPosting(
        posting=_posting(company=company, role=role, url=url),
        score=score,
        rationale="test",
    )


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


def test_empty_list_returns_empty() -> None:
    assert top_per_company([]) == []


def test_single_posting_passes_through() -> None:
    sp = _scored()
    assert top_per_company([sp]) == [sp]


def test_unique_companies_all_pass_through() -> None:
    sp1 = _scored(company="Acme", url="https://example.com/1")
    sp2 = _scored(company="BetaCorp", url="https://example.com/2")
    result = top_per_company([sp1, sp2])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Best-score selection
# ---------------------------------------------------------------------------


def test_highest_score_kept_when_duplicate_company() -> None:
    low = _scored(score=0.4, url="https://example.com/1")
    high = _scored(score=0.8, url="https://example.com/2")
    result = top_per_company([low, high])
    assert len(result) == 1
    assert result[0].score == 0.8


def test_highest_score_kept_regardless_of_order() -> None:
    high = _scored(score=0.9, url="https://example.com/1")
    low = _scored(score=0.3, url="https://example.com/2")
    result = top_per_company([high, low])
    assert len(result) == 1
    assert result[0].score == 0.9


def test_three_postings_same_company_keeps_best() -> None:
    a = _scored(score=0.5, url="https://example.com/1")
    b = _scored(score=0.7, url="https://example.com/2")
    c = _scored(score=0.6, url="https://example.com/3")
    result = top_per_company([a, b, c])
    assert len(result) == 1
    assert result[0].score == 0.7


# ---------------------------------------------------------------------------
# Case-insensitive company matching
# ---------------------------------------------------------------------------


def test_company_name_case_insensitive() -> None:
    lower = _scored(company="acme", score=0.4, url="https://example.com/1")
    upper = _scored(company="ACME", score=0.8, url="https://example.com/2")
    result = top_per_company([lower, upper])
    assert len(result) == 1
    assert result[0].score == 0.8


def test_mixed_case_company_casing_preserved() -> None:
    sp = _scored(company="DeepMind", score=0.9)
    result = top_per_company([sp])
    assert result[0].posting.company == "DeepMind"


# ---------------------------------------------------------------------------
# Output ordering
# ---------------------------------------------------------------------------


def test_output_order_matches_first_appearance() -> None:
    acme = _scored(company="Acme", url="https://example.com/1")
    beta = _scored(company="BetaCorp", url="https://example.com/2")
    gamma = _scored(company="Gamma", url="https://example.com/3")
    result = top_per_company([acme, beta, gamma])
    assert [r.posting.company for r in result] == ["Acme", "BetaCorp", "Gamma"]


def test_duplicate_company_does_not_shift_position() -> None:
    acme1 = _scored(company="Acme", score=0.4, url="https://example.com/1")
    beta = _scored(company="BetaCorp", url="https://example.com/2")
    acme2 = _scored(company="Acme", score=0.9, url="https://example.com/3")
    result = top_per_company([acme1, beta, acme2])
    # Acme appears first, BetaCorp second
    assert result[0].posting.company == "Acme"
    assert result[1].posting.company == "BetaCorp"


# ---------------------------------------------------------------------------
# Mixed scenario
# ---------------------------------------------------------------------------


def test_mixed_stream_deduplicates_per_company() -> None:
    gh1 = _scored(company="Acme", score=0.6, url="https://example.com/1")
    gh2 = _scored(company="Acme", score=0.8, url="https://example.com/2")
    beta = _scored(company="BetaCorp", score=0.5, url="https://example.com/3")
    gamma1 = _scored(company="Gamma", score=0.3, url="https://example.com/4")
    gamma2 = _scored(company="Gamma", score=0.9, url="https://example.com/5")
    result = top_per_company([gh1, gh2, beta, gamma1, gamma2])
    assert len(result) == 3
    scores = {r.posting.company: r.score for r in result}
    assert scores["Acme"] == 0.8
    assert scores["BetaCorp"] == 0.5
    assert scores["Gamma"] == 0.9
