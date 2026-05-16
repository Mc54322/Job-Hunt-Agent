"""Tests for the ATS detector."""

from __future__ import annotations

from jobassist.sources.detector import detect_ats

# ---------------------------------------------------------------------------
# URL-based detection
# ---------------------------------------------------------------------------


def test_detects_greenhouse_from_url() -> None:
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"


def test_detects_lever_from_url() -> None:
    assert detect_ats("https://jobs.lever.co/acme/abc-001") == "lever"


def test_detects_workday_from_url() -> None:
    assert detect_ats("https://amazon.wd3.myworkdayjobs.com/en-US/External") == "workday"


def test_detects_workday_different_wd_number() -> None:
    assert detect_ats("https://barclays.wd5.myworkdayjobs.com/External_Careers") == "workday"


def test_detects_ashby_from_url() -> None:
    assert detect_ats("https://jobs.ashbyhq.com/acme") == "ashby"


def test_detects_reed_from_url() -> None:
    assert detect_ats("https://www.reed.co.uk/jobs/software-engineer/12345") == "reed"


def test_detects_smartrecruiters_from_url() -> None:
    assert detect_ats("https://jobs.smartrecruiters.com/Acme/123") == "smartrecruiters"


def test_returns_none_for_unknown_url() -> None:
    assert detect_ats("https://careers.acme.com/jobs") is None


def test_returns_none_for_linkedin() -> None:
    assert detect_ats("https://www.linkedin.com/jobs/view/123") is None


# ---------------------------------------------------------------------------
# HTML-based detection (fallback)
# ---------------------------------------------------------------------------


def test_detects_greenhouse_from_html() -> None:
    html = '<script src="https://boards.greenhouse.io/embed/job_board.js?for=acme"></script>'
    assert detect_ats("https://careers.acme.com", html) == "greenhouse"


def test_detects_lever_from_html() -> None:
    html = '<div id="lever-jobs" data-url="https://jobs.lever.co/acme"></div>'
    assert detect_ats("https://careers.acme.com", html) == "lever"


def test_detects_workday_from_html() -> None:
    html = '<a href="https://acme.myworkdayjobs.com/en-US/careers">Apply</a>'
    assert detect_ats("https://careers.acme.com", html) == "workday"


def test_url_takes_priority_over_html() -> None:
    # URL says greenhouse, HTML says lever — URL wins
    html = '<a href="https://jobs.lever.co/acme">View on Lever</a>'
    assert detect_ats("https://boards.greenhouse.io/acme", html) == "greenhouse"


def test_returns_none_when_html_has_no_ats_signals() -> None:
    assert detect_ats("https://careers.acme.com", "<p>We are hiring!</p>") is None


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_url_detection_is_case_insensitive() -> None:
    assert detect_ats("https://BOARDS.GREENHOUSE.IO/acme") == "greenhouse"


def test_html_detection_is_case_insensitive() -> None:
    html = "https://BOARDS.GREENHOUSE.IO/embed"
    assert detect_ats("https://careers.acme.com", html) == "greenhouse"
