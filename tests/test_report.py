"""Tests for the Markdown report generator."""

from __future__ import annotations

from pathlib import Path

from jobassist.report import _render, generate_report
from jobassist.schemas import JobPosting, JobQuery, ScoredPosting


def _sp(
    company: str = "Acme",
    role: str = "Software Engineer",
    location: str = "London, UK",
    score: float = 0.8,
    source: str = "greenhouse",
    salary: str | None = None,
    description: str | None = None,
    rationale: str = "Strong match.",
) -> ScoredPosting:
    return ScoredPosting(
        posting=JobPosting(
            company=company,
            role=role,
            location=location,
            url=f"https://example.com/{company.lower()}",
            source=source,
            salary_raw=salary,
            description=description,
        ),
        score=score,
        rationale=rationale,
    )


_QUERY = JobQuery(role="Software Engineer", job_type="full-time", location="London, UK")
_QUERY_NO_LOC = JobQuery(role="Data Analyst", job_type="contract")


# ---------------------------------------------------------------------------
# _render — content
# ---------------------------------------------------------------------------


def test_render_includes_role_in_title() -> None:
    md = _render([_sp()], _QUERY)
    assert "Software Engineer" in md


def test_render_includes_location_in_title() -> None:
    md = _render([_sp()], _QUERY)
    assert "London, UK" in md


def test_render_omits_location_when_not_in_query() -> None:
    md = _render([_sp()], _QUERY_NO_LOC)
    assert "London, UK" not in md.splitlines()[0]


def test_render_has_summary_table() -> None:
    md = _render([_sp()], _QUERY)
    assert "## Summary" in md
    assert "| # |" in md


def test_render_has_postings_section() -> None:
    md = _render([_sp()], _QUERY)
    assert "## Postings" in md


def test_render_includes_score() -> None:
    md = _render([_sp(score=0.87)], _QUERY)
    assert "0.87" in md


def test_render_includes_rationale() -> None:
    md = _render([_sp(rationale="Excellent Python skills.")], _QUERY)
    assert "Excellent Python skills." in md


def test_render_includes_salary_when_present() -> None:
    md = _render([_sp(salary="£60,000")], _QUERY)
    assert "£60,000" in md


def test_render_salary_dash_when_none() -> None:
    md = _render([_sp(salary=None)], _QUERY)
    assert "| — |" in md or "| —" in md


def test_render_includes_description_when_present() -> None:
    md = _render([_sp(description="Build distributed systems.")], _QUERY)
    assert "Build distributed systems." in md


def test_render_sorted_by_score_descending() -> None:
    low = _sp(company="Low", score=0.3)
    high = _sp(company="High", score=0.9)
    md = _render([low, high], _QUERY)
    assert md.index("High") < md.index("Low")


def test_render_empty_results() -> None:
    md = _render([], _QUERY)
    assert "No postings scored" in md
    assert "## Summary" not in md


def test_render_multiple_postings_numbered() -> None:
    results = [_sp(company=f"Co{i}", score=0.9 - i * 0.1) for i in range(3)]
    md = _render(results, _QUERY)
    assert "### 1." in md
    assert "### 2." in md
    assert "### 3." in md


def test_render_includes_generated_date() -> None:
    from datetime import date
    md = _render([_sp()], _QUERY)
    assert date.today().isoformat() in md


# ---------------------------------------------------------------------------
# generate_report — file I/O
# ---------------------------------------------------------------------------


def test_generate_report_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    generate_report([_sp()], _QUERY, out)
    assert out.exists()


def test_generate_report_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "dir" / "report.md"
    generate_report([_sp()], _QUERY, out)
    assert out.exists()


def test_generate_report_content_is_valid_markdown(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    generate_report([_sp()], _QUERY, out)
    content = out.read_text()
    assert content.startswith("# Job Search Report")
    assert "## Summary" in content


def test_generate_report_is_utf8(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    generate_report([_sp(salary="£50,000")], _QUERY, out)
    content = out.read_bytes().decode("utf-8")
    assert "£50,000" in content


# ---------------------------------------------------------------------------
# CLI integration — --report flag
# ---------------------------------------------------------------------------


def test_cli_search_help_shows_report_option() -> None:
    from typer.testing import CliRunner

    from jobassist.cli import app
    result = CliRunner().invoke(app, ["search", "--help"])
    assert "--report" in result.output
